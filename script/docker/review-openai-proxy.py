"""HTTP CONNECT for api.openai.com:443 on the private review bridge. TLS stays end-to-end."""
import asyncio
import ipaddress
import os

TARGET = b"api.openai.com:443"
HEADER_LIMIT = 8192


async def copy_stream(source, target):
    while data := await asyncio.wait_for(source.read(65536), 300):
        target.write(data)
        await target.drain()
    target.write_eof()


async def serve():
    address = ipaddress.IPv4Address(os.environ["REVIEW_BRIDGE_GATEWAY"])
    network = ipaddress.IPv4Network(os.environ["REVIEW_BRIDGE_SUBNET"])
    if not network.is_private or address not in network or address.is_loopback:
        raise ValueError("Expected a private review bridge")
    capacity = asyncio.Semaphore(24)

    async def handle(client, downstream):
        peer = ipaddress.ip_address(downstream.get_extra_info("peername")[0])
        upstream = None
        pumps = []
        try:
            if peer not in network or capacity.locked():
                return
            async with capacity:
                headers = await asyncio.wait_for(client.readuntil(b"\r\n\r\n"), 8)
                first = headers.split(b"\r\n", 1)[0].split()
                if len(first) != 3 or first[:2] != [b"CONNECT", TARGET] or first[2] not in (b"HTTP/1.0", b"HTTP/1.1"):
                    downstream.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    await downstream.drain()
                    return
                reader, upstream = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", int(os.environ["REVIEW_HOST_PROXY_PORT"]), limit=HEADER_LIMIT), 8)
                upstream.write(b"CONNECT " + TARGET + b" HTTP/1.1\r\nHost: " + TARGET + b"\r\n\r\n")
                await upstream.drain()
                reply = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 12)
                if reply.split(b"\r\n", 1)[0].split()[1:2] != [b"200"]:
                    downstream.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                    await downstream.drain()
                    return
                downstream.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await downstream.drain()
                pumps = [asyncio.create_task(copy_stream(client, upstream)),
                         asyncio.create_task(copy_stream(reader, downstream))]
                await asyncio.gather(*pumps)
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            for pump in pumps:
                pump.cancel()
            if pumps:
                await asyncio.gather(*pumps, return_exceptions=True)
            if upstream:
                upstream.close()
            downstream.close()

    async with await asyncio.start_server(handle, str(address), int(os.environ["REVIEW_OPENAI_RELAY_PORT"]), limit=HEADER_LIMIT) as server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(serve())
