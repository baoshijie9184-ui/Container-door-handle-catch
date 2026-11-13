// ECS-only fixture; reuse the pinned Langfuse worker's own AWS SDK dependency.
// Never print endpoints, credentials, signed URLs or raw provider errors.
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';

const [phase, privateFile, receiptFile] = process.argv.slice(2);
const payload = 'doorhandle-oss-compatibility-fixture-v1';
let client;
try {
  if (!['prepare', 'cleanup'].includes(phase) || !privateFile?.startsWith('/') || !receiptFile?.startsWith('/')) throw Error('input');
  const require = createRequire('/app/worker/node_modules/@langfuse/shared/package.json');
  const { S3Client, PutObjectCommand, GetObjectCommand, DeleteObjectCommand } = require('@aws-sdk/client-s3');
  const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');
  const required = ['LF_S3_BUCKET', 'LF_S3_REGION', 'LF_S3_ENDPOINT', 'LF_S3_ACCESS_KEY_ID', 'LF_S3_SECRET_ACCESS_KEY'];
  if (required.some(key => !process.env[key])) throw Error('configuration');
  client = new S3Client({ region: process.env.LF_S3_REGION, endpoint: process.env.LF_S3_ENDPOINT,
    forcePathStyle: process.env.LF_S3_FORCE_PATH_STYLE === 'true', maxAttempts: 1,
    requestHandler: { connectionTimeout: 5000, requestTimeout: 15000 },
    credentials: { accessKeyId: process.env.LF_S3_ACCESS_KEY_ID, secretAccessKey: process.env.LF_S3_SECRET_ACCESS_KEY } });
  const bucket = process.env.LF_S3_BUCKET;
  let report = { schemaVersion: 1, phase, status: 'PENDING', serverReadWrite: false, presignedReadWrite: false, browserCors: 'PENDING' };
  if (phase === 'prepare') {
    const id = randomUUID();
    const keys = ['server.txt', 'presigned.txt', 'browser.txt'].map(name => `langfuse/compatibility/${id}/${name}`);
    // Persist ownership before any write, so a failed preparation remains recoverable.
    await mkdir(dirname(privateFile), { recursive: true });
    const manifest = { schemaVersion: 1, runId: id, keys, payload,
      storage: { bucket, endpoint: process.env.LF_S3_ENDPOINT, region: process.env.LF_S3_REGION } };
    await writeFile(privateFile, JSON.stringify(manifest), { mode: 0o600, flag: 'wx' });
    await client.send(new PutObjectCommand({ Bucket: bucket, Key: keys[0], Body: payload, ContentType: 'text/plain' }));
    const fetched = await client.send(new GetObjectCommand({ Bucket: bucket, Key: keys[0] }));
    if (await fetched.Body.transformToString() !== payload) throw Error('server_content');
    report.serverReadWrite = true;
    const put = await getSignedUrl(client, new PutObjectCommand({ Bucket: bucket, Key: keys[1], ContentType: 'text/plain' }), { expiresIn: 300 });
    const get = await getSignedUrl(client, new GetObjectCommand({ Bucket: bucket, Key: keys[1] }), { expiresIn: 300 });
    const uploaded = await fetch(put, { method: 'PUT', body: payload, headers: { 'Content-Type': 'text/plain' }, signal: AbortSignal.timeout(15000) });
    if (!uploaded.ok) throw Error('presigned_put');
    const downloaded = await fetch(get, { signal: AbortSignal.timeout(15000) });
    if (!downloaded.ok || await downloaded.text() !== payload) throw Error('presigned_get');
    report.presignedReadWrite = true;
    manifest.browserPut = await getSignedUrl(client, new PutObjectCommand({ Bucket: bucket, Key: keys[2], ContentType: 'text/plain' }), { expiresIn: 300 });
    manifest.browserGet = await getSignedUrl(client, new GetObjectCommand({ Bucket: bucket, Key: keys[2] }), { expiresIn: 300 });
    await writeFile(privateFile, JSON.stringify(manifest), { mode: 0o600 });
    report.status = 'SERVER_PASSED_BROWSER_PENDING';
  } else {
    const manifest = JSON.parse(await readFile(privateFile, 'utf8'));
    if (manifest.schemaVersion !== 1 || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(manifest.runId)
      || manifest.storage?.bucket !== bucket || manifest.storage?.endpoint !== process.env.LF_S3_ENDPOINT || manifest.storage?.region !== process.env.LF_S3_REGION
      || JSON.stringify(manifest.keys) !== JSON.stringify(['server.txt', 'presigned.txt', 'browser.txt'].map(name => `langfuse/compatibility/${manifest.runId}/${name}`))) throw Error('ownership');
    for (const key of manifest.keys) await client.send(new DeleteObjectCommand({ Bucket: bucket, Key: key }));
    report = { schemaVersion: 1, phase, status: 'CLEANED', ownedObjects: 3 };
    // Overwrite short-lived signed URLs after cleanup; only safe ownership evidence remains.
    await writeFile(privateFile, JSON.stringify({ schemaVersion: 1, runId: manifest.runId, keys: manifest.keys, storage: manifest.storage, cleaned: true }), { mode: 0o600 });
  }
  await mkdir(dirname(receiptFile), { recursive: true });
  await writeFile(receiptFile, JSON.stringify(report, null, 2) + '\n');
  process.stdout.write(`OSS_COMPATIBILITY_${report.status}\n`);
} catch {
  process.stderr.write('OSS_COMPATIBILITY_FAILED\n');
  process.exitCode = 1;
} finally { client?.destroy(); }
