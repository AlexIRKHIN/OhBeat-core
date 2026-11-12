// Inside the test container "localhost" is the container itself. The browser of the test must still
// open http://localhost:5173 and upload to http://localhost:9000: presigned links are signed for that
// host (CLAUDE.md, "ссылки presigned должны открываться из браузера"). So the ports are forwarded to
// the services of the docker network, byte for byte — the Host header and the signatures stay intact.
import net from "node:net";

const FORWARDS: [number, string][] = [
  [5173, process.env.E2E_FRONTEND ?? "frontend:5173"],
  [9000, process.env.E2E_MINIO ?? "minio:9000"],
  [8100, process.env.E2E_YOOKASSA ?? "yookassa-mock:8100"],
];

function forward(port: number, target: string): Promise<net.Server> {
  const [host, targetPort] = target.split(":");
  const server = net.createServer((client) => {
    const upstream = net.connect(Number(targetPort), host);
    client.pipe(upstream).pipe(client);
    const close = () => (client.destroy(), upstream.destroy());
    client.on("error", close);
    upstream.on("error", close);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

async function waitFor(url: string, seconds: number): Promise<void> {
  for (let i = 0; i < seconds; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // the frontend container may still be installing packages
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`${url} did not answer in ${seconds} s`);
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  const servers = await Promise.all(FORWARDS.map(([port, target]) => forward(port, target)));
  await waitFor("http://localhost:5173/", 300);
  await waitFor("http://localhost:5173/v1/dictionaries", 120);
  return async () => {
    await Promise.all(servers.map((s) => new Promise((r) => s.close(r))));
  };
}
