// `npm run dev`: starts the Python server (unless one is already listening) and the Expo dev server
// with hot reload. Open the Expo address it prints; API calls are forwarded to the Python server.
const { spawn, execSync } = require("child_process");
const net = require("net");
const path = require("path");

const port = Number(process.env.CHECKER_PORT || 8000);
process.env.CHECKER_URL = `http://127.0.0.1:${port}`;
const kids = [];

const run = (cmd, args, opts = {}) => {
  const p = spawn(cmd, args, { stdio: "inherit", shell: true, ...opts });
  kids.push(p);
  p.on("exit", stop);
  return p;
};

function stop() {
  for (const p of kids.splice(0)) {
    try {
      if (process.platform === "win32") execSync(`taskkill /pid ${p.pid} /T /F`, { stdio: "ignore" });
      else p.kill();
    } catch {}
  }
  process.exit(0);
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);

const probe = net.connect(port, "127.0.0.1");
probe.on("connect", () => {
  probe.destroy();
  console.log(`Using the Python server already running on port ${port}.`);
  run("npx", ["expo", "start", "--web"]);
});
probe.on("error", () => {
  console.log(`Starting the Python server on port ${port}...`);
  run("uv", ["run", "python", "-m", "checker.cli", "serve", "--no-browser"], { cwd: path.resolve(__dirname, "../..") });
  run("npx", ["expo", "start", "--web"]);
});
