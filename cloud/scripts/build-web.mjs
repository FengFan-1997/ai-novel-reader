import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectDir = path.resolve(scriptDir, "../..");
const outputDir = path.join(projectDir, "cloud/web/dist");

await rm(outputDir, { recursive: true, force: true });
await mkdir(path.join(outputDir, "static"), { recursive: true });

// The modern Flask shell may replace the former index template with
// legacy.html during a UI migration.  Keep cloud builds reproducible across
// both layouts instead of requiring the old template to be restored.
let sourceHtml;
try {
  sourceHtml = await readFile(path.join(projectDir, "templates/index.html"), "utf8");
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
  sourceHtml = await readFile(path.join(projectDir, "templates/legacy.html"), "utf8");
}
const cloudHtml = sourceHtml
  .replace(
    "</head>",
    '    <link rel="stylesheet" href="/cloud/cloud.css?v=1">\n' +
    '    <script src="/cloud/cloud-client.js?v=2"></script>\n' +
    "</head>",
  );

await writeFile(path.join(outputDir, "index.html"), cloudHtml);
await cp(path.join(projectDir, "static/css"), path.join(outputDir, "static/css"), { recursive: true });
await cp(path.join(projectDir, "static/js"), path.join(outputDir, "static/js"), { recursive: true });
await cp(path.join(projectDir, "cloud/web/public"), outputDir, { recursive: true });
await cp(path.join(projectDir, "cloud/web/vercel.deploy.json"), path.join(outputDir, "vercel.json"));

console.log(`Built cloud frontend at ${outputDir}`);
