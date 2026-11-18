"""Forward the local Compose stack's OSS TLS connections via its host proxy."""

import asyncio
import ipaddress
import os
import re


async def transfer(source, target):
    while data := await asyncio.wait_for(source.read(65536), timeout=180):
        target.write(data)
        await target.drain()
    target.write_eof()


async def main():
    host = os.environ['OSS_UPLOAD_HOST']
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.oss-[a-z0-9-]+\.aliyuncs\.com', host):
        raise ValueError('Expected an Alibaba OSS bucket hostname')
    proxy = ipaddress.IPv4Address(os.environ['OSS_LOCAL_PROXY_HOST'])
    port = int(os.environ['OSS_LOCAL_PROXY_PORT'])
    if not proxy.is_private or proxy.is_loopback or not 1024 <= port <= 65535:
        raise ValueError('Expected a proxy reachable through the local Docker bridge')
    connect = f'CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n'.encode('ascii')
    available = asyncio.Semaphore(32)

    async def handle(client, client_writer):
        proxy_writer = None
        pumps = []
        try:
            if available.locked():
                return
            async with available:
                proxy_reader, proxy_writer = await asyncio.wait_for(asyncio.open_connection(str(proxy), port), 10)
                proxy_writer.write(connect)
                await proxy_writer.drain()
                headers = await asyncio.wait_for(proxy_reader.readuntil(b'\r\n\r\n'), 12)
                if not re.match(rb'HTTP/1\.[01] 200[ \r]', headers):
                    raise ConnectionError('The host proxy rejected the OSS tunnel')
                pumps = [asyncio.create_task(transfer(client, proxy_writer)),
                         asyncio.create_task(transfer(proxy_reader, client_writer))]
                await asyncio.gather(*pumps)
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
            print(f'OSS tunnel closed ({type(error).__name__})', flush=True)
        finally:
            for pump in pumps:
                pump.cancel()
            if pumps:
                await asyncio.gather(*pumps, return_exceptions=True)
            if proxy_writer is not None:
                proxy_writer.close()
            client_writer.close()

    async with await asyncio.start_server(handle, '0.0.0.0', 443) as server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
