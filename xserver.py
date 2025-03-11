import asyncio
import logging
import time
import os
from aioquic.asyncio import connect, serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import HandshakeCompleted, ProtocolNegotiated    
from aioquic.asyncio import connect, QuicConnectionProtocol
from aioquic.h3.events import WebTransportStreamDataReceived
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import (
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from typing import Optional

logging.basicConfig(level=logging.INFO)

# Server Implementation
class WebTransportServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http: Optional[H3Connection] = None
        self.hello_initiated=False
        self.sessions = {}
        
    def make_session(self):
        quic_client = self._http._quic
        stream_id = quic_client.get_next_available_stream_id()
        print('stream id',stream_id)
        self._http.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"CONNECT"),
                (b":scheme", b"https"),
                (b":authority", b"localhost"),
                (b":path", b"/"),
                (b":protocol", b"webtransport"),
            ],
        )
        print('sendig headers')
        self.transmit()
        return stream_id 
    
    def create_new_webtransport_stream(self, session_id):
        stream_id = self._http.create_webtransport_stream(session_id)
        self.transmit()
        stream = self._http._get_or_create_stream(stream_id)
        stream.frame_type = 0x41
        stream.session_id = session_id
        self.sessions[session_id]['1'] = stream_id
        return stream_id


    async def send_init_segment(self, stream_id: int):
        """
        Send the initialization segment (init.mp4) over a dedicated WebTransport stream.
        """
        init_segment_path = "video/init.mp4"  # Path to the initialization segment file

        if not os.path.exists(init_segment_path):
            print(f"Initialization segment not found: {init_segment_path}")
            return

        try:
            # Read and send the initialization segment
            with open(init_segment_path, "rb") as f:
                init_data = f.read()
                self._quic.send_stream_data(stream_id, init_data, end_stream=True)
                self.transmit()
                print(f"Sent initialization segment ({len(init_data)} bytes) on stream {stream_id}")
        except Exception as e:
            print(f"Error sending initialization segment: {e}")
        
    async def send_manifest(self, stream_id: int):
        """
        Send the manifest.mpd file over the specified WebTransport stream.
        """
        manifest_path = os.path.join('video', "output.mpd")  # Adjust path as needed
        try:
            with open(manifest_path, "rb") as f:
                data = f.read()
                logging.info(f"Sending manifest ({len(data)} bytes)")
                self._quic.send_stream_data(stream_id, data, end_stream=True)
                self.transmit()
        except Exception as e:
            logging.error(f"Error sending manifest: {e}")


    async def send_audio(self, stream_id: int):
        """
        Stream audio segments (.m4s files) over the specified WebTransport stream.
        Only streams files matching the naming pattern for audio (e.g., chunk-stream1-*.m4s).
        """
        # Filter and sort audio files based on the naming convention
        audio_files = sorted(
            [f for f in os.listdir('video') if f.startswith("chunk-stream1-") and f.endswith(".m4s")]
        )
        logging.info(f"Streaming {len(audio_files)} audio segments...")

        for i, file_name in enumerate(audio_files):
            file_path = os.path.join('video', file_name)
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
                    logging.info(f"Sending segment {file_name} ({len(data)} bytes)")
                    self._quic.send_stream_data(stream_id, data, False)
                    self.transmit()
            except Exception as e:
                logging.error(f"Error reading or sending {file_name}: {e}")
                break

            # Simulate segment duration (e.g., 2 seconds per segment)
            await asyncio.sleep(2)
    
    async def helloworld(self, stream_id: int):
        i = 0
        print(stream_id)
        while True:
            if not self.hello_initiated:
                self.hello_initiated=True
                self._quic.send_stream_data(stream_id, b"hellostream", False)
            else:
                self._quic.send_stream_data(stream_id, b"Hello", False)
                print('sending hello ', i)
                i+=1
            self.transmit()
            await asyncio.sleep(1)
    
    def http_event_received(self, event: H3Event):
        print('HTTP received',event)
        if isinstance(event, WebTransportStreamDataReceived):
            print(f"Received: {event.data.decode().strip()}")
            data = event.data.decode().strip()
            if data == 'hellohere':
                asyncio.ensure_future(self.helloworld(event.stream_id))

        if isinstance(event, HeadersReceived):
            print(f"Received headers: {event.headers}")
            session_id = event.stream_id
            if session_id not in self.sessions:
                self.sessions[session_id] = {}
            stream_id_manifest = self.create_new_webtransport_stream(session_id)
            stream_id_audio = self.create_new_webtransport_stream(session_id)
            stream_id_init = self.create_new_webtransport_stream(session_id)
            self._quic.send_stream_data(stream_id_manifest, b"manifesthere", False)
            self.transmit()
            self._quic.send_stream_data(stream_id_init, b"init", False)
            self.transmit()
            self._quic.send_stream_data(stream_id_audio, b"audiohere", False)
            self.transmit()
            asyncio.ensure_future(self.send_manifest(stream_id_manifest))
            asyncio.ensure_future(self.send_init_segment(stream_id_init))
            asyncio.ensure_future(self.send_audio(stream_id_audio))

    def quic_event_received(self, event):
        print('QUIC received',event)
        if isinstance(event, ProtocolNegotiated):
            if event.alpn_protocol in H3_ALPN:
                print('creating h3 connection')
                self._http = H3Connection(self._quic, enable_webtransport=True)
        elif isinstance(event, HandshakeCompleted):
            logging.info("Handshake completed, ready for WebTransport session.")  
        elif self._http is not None:
            print('handling event')
            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event) 

async def run_server():
    configuration = QuicConfiguration(is_client=False,alpn_protocols=H3_ALPN,max_datagram_frame_size=65536,)
    configuration.load_cert_chain("ssl_cert.pem", "ssl_key.pem")
    await serve("localhost", 4433, configuration=configuration, create_protocol=WebTransportServerProtocol)
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(run_server())