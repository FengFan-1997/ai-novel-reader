import { DeleteObjectCommand, GetObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

/**
 * R2 is deliberately optional.  A contribution remains a valid P2P seed when
 * the hot cache is disabled or full; no audio is ever proxied through Render.
 */
export function createObjectStore(env = process.env) {
  const endpoint = env.R2_ENDPOINT || "";
  const bucket = env.R2_BUCKET || "";
  const accessKeyId = env.R2_ACCESS_KEY_ID || "";
  const secretAccessKey = env.R2_SECRET_ACCESS_KEY || "";
  if (!endpoint || !bucket || !accessKeyId || !secretAccessKey) {
    return {
      enabled: false,
      async uploadUrl() { return null; },
      async downloadUrl() { return null; },
      async inspectObject() { return null; },
      async deleteObject() { return false; },
    };
  }
  const client = new S3Client({
    region: "auto",
    endpoint,
    credentials: { accessKeyId, secretAccessKey },
  });
  return {
    enabled: true,
    async uploadUrl(key, contentType = "audio/ogg") {
      return getSignedUrl(client, new PutObjectCommand({ Bucket: bucket, Key: key, ContentType: contentType }), { expiresIn: 15 * 60 });
    },
    async downloadUrl(key) {
      return getSignedUrl(client, new GetObjectCommand({ Bucket: bucket, Key: key }), { expiresIn: 10 * 60 });
    },
    async deleteObject(key) {
      await client.send(new DeleteObjectCommand({ Bucket: bucket, Key: key }));
      return true;
    },
    async inspectObject(key) {
      const result = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
      return { byteSize: Number(result.ContentLength || 0), contentType: result.ContentType || "" };
    },
  };
}
