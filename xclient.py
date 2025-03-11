import asyncio
import logging
import subprocess
from just_playback import Playback
import os
from aioquic.asyncio import connect, serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import HandshakeCompleted,ProtocolNegotiated
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.asyncio import connect, QuicConnectionProtocol
from aioquic.h3.events import WebTransportStreamDataReceived
from aioquic.quic.logger import QuicFileLogger

class WebTransportClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream_id = None
        self.queues = {}
    
    async def output_response(self,stream_id=None):
        i=0
        while i<5:
            await asyncio.sleep(1)
            if not self.queue.empty():
                print(self.queue.get_nowait(), i)
                i+=1
            else:
                print('waiting for response')
        self._quic.send_stream_data(self.hellostream, b"FIN", True)
        self.transmit()
    
    async def receive_manifest(self,stream_id):
        print("Receiving manifest on stream...", stream_id)
        manifest_data = b""  # Buffer to store the manifest data

        while True:
            try:
                # Wait for data from the queue associated with this stream
                event = await self.queues[stream_id].get()
                data = event.data
                fin = event.stream_ended
                manifest_data += data
                if fin:  # End of stream (empty data indicates FIN flag)
                    break
            except Exception as e:
                logging.error(f"Error receiving manifest: {e}")
                break

        # Save the received manifest to a file
        manifest_path = "received_manifest.mpd"
        try:
            with open(manifest_path, "wb") as f:
                f.write(manifest_data)
            f.close()
            print(f"Manifest saved to {manifest_path}")
        except Exception as e:
            logging.error(f"Error saving manifest: {e}")

    async def receive_init_segment(self,stream_id):
        print("Receiving init segment on stream...", stream_id)
        init_data = b""
        while True:
            try:
                event = await self.queues[stream_id].get()
                data = event.data
                fin = event.stream_ended
                init_data += data
                if fin:
                    break
            except Exception as e:
                logging.error(f"Error receiving init segment: {e}")
                break
        init_segment_path = "client_received/received_init.mp4"
        try:
            with open(init_segment_path, "wb") as f:
                f.write(init_data)
            print(f"Initialization segment saved to {init_segment_path}")
        except Exception as e:
            logging.error(f"Error saving initialization segment: {e}")

    async def play_media(self):
        init_file = "client_received/received_init.mp4"
        with open(init_file, "rb") as init:
        output_pipe.write(init.read())

        while True:
            segment = segment_queue.get()  # Fetch the next segment from the queue
            if segment is None:  # Sentinel value to stop playback
                break

            # Write the segment to the output pipe
            with open(segment, "rb") as seg:
                output_pipe.write(seg.read())
    async def start_ffmpeg():
    # FFmpeg command to play video and audio from pipes
        ffmpeg_command = [
            "ffmpeg",
            "-i", "pipe:0",  # Video input from pipe
            "-i", "pipe:1",  # Audio input from pipe
            "-c:v", "copy",  # Copy video codec
            "-c:a", "aac",   # Re-encode audio to AAC (optional)
            "-f", "matroska", # Output format
            "-"              # Output to stdout (for playback)
        ]

        # Start FFmpeg process
        ffmpeg_process = subprocess.Popen(
            ffmpeg_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        return ffmpeg_process


    async def receive_audio(self,stream_id):
        """
        Receive audio segments (.m4s) over a dedicated WebTransport stream
        and play them in real time using the previously received init.mp4.
        """
        print(f"Receiving audio segments on stream {stream_id}...")
        init_segment_path = "client_received/received_init.mp4"  # Path to the previously saved init segment

        if not os.path.exists(init_segment_path):
            print(f"Initialization segment not found: {init_segment_path}")
            return

        # Start an FFmpeg subprocess for real-time playback
        ffmpeg_process = subprocess.Popen(
            [
                "ffmpeg",
                "-i", "concat:" + init_segment_path + "|-",  # Concatenate init.mp4 with incoming segments
                "-f", "mp3",       # Output format (can be adjusted based on your needs)
                "-nodisp",         # No display (for audio-only playback)
                "-autoexit",       # Exit when playback is done
                "pipe:1"           # Output to stdout (not used here, but required by ffmpeg)
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=10**6
        )

        try:
            while True:
                # Wait for data from the queue associated with this stream
                
                event = await self.queues[stream_id].get()
                data = event.data
                fin = event.stream_ended
                ffmpeg_process.stdin.write(data)
                ffmpeg_process.stdin.flush()
                print(f"Sent audio segment ({len(data)} bytes) to FFmpeg")
                if fin:
                    break

                # Write the received segment to FFmpeg's stdin for real-time playback
                

        except Exception as e:
            logging.error(f"Error receiving or playing audio: {e}")

        finally:
            # Close FFmpeg process
            ffmpeg_process.stdin.close()
            ffmpeg_process.wait()
            print("FFmpeg process closed.")


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

    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated):
            if event.alpn_protocol in H3_ALPN:
                print('creating h3 connection')
                self._http = H3Connection(self._quic, enable_webtransport=True)
        if isinstance(event, HandshakeCompleted):
            print("Client connected, opening stream.")
        if self._http is not None:
            for http_event in self._http.handle_event(event):
                self.http_event_received(http_event)
    def http_event_received(self, event):
        #print('HTTP received',event)
        if isinstance(event, WebTransportStreamDataReceived):
            try:
                if event.data.decode() == 'audiohere':
                    self.queues[event.stream_id] = asyncio.Queue()
                    self.audio_stream_id = event.stream_id
                    asyncio.ensure_future(self.play_media())
                #     video_thread = threading.Thread(
                #     target=playback_segments,
                #     args=(video_init_file, video_queue, ffmpeg_process.stdin, "video"),
                # )
                elif event.data.decode() =='videohere':
                    self.queues[event.stream_id] = asyncio.Queue()
                    self.video_stream_id = event.stream_id
                    
                elif event.data.decode().strip() == 'manifesthere':
                    self.queues[event.stream_id] = asyncio.Queue()
                    asyncio.ensure_future(self.receive_manifest(event.stream_id))
                elif event.data.decode().strip() == 'init':
                    self.queues[event.stream_id] = asyncio.Queue()
                    asyncio.ensure_future(self.receive_init_segment(event.stream_id))
                else:
                    self.queues[event.stream_id].put_nowait(event)      
            except UnicodeDecodeError as e:
                #Receiving Audio
                self.queues[event.stream_id].put_nowait(event)


async def create_webtransport_stream(protocol,session_id):
    stream_id = protocol._http.create_webtransport_stream(session_id)
    protocol.transmit()
    stream = protocol._http._get_or_create_stream(stream_id)
    stream.frame_type = 0x41
    stream.session_id = session_id
    return stream_id

async def helloworld(protocol,session_id):
    stream_id1 = await create_webtransport_stream(protocol,session_id)
    protocol._quic.send_stream_data(stream_id1, b"hellohere", False)
    protocol.transmit()
    await protocol.output_response(stream_id = stream_id1)

async def receive_media(protocol):
    session_id = protocol.make_session()
    #await helloworld(protocol,session_id)
    
async def start_client():
    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=H3_ALPN,
        max_datagram_frame_size=65536,
    )

    configuration.quic_logger = QuicFileLogger("client.log")
    configuration.load_verify_locations('pycacert.pem')
    async with connect("localhost", 4433, configuration=configuration, create_protocol=WebTransportClientProtocol) as protocol:
        await protocol.wait_connected()
        await receive_media(protocol)
        
        await asyncio.sleep(200)
        #await protocol.output_response() # Keep client alive to receive messages

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_client())