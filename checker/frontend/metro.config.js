const http = require("http");
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);

// In `npm run dev` the page comes from Expo, but data, images and PDFs live on the Python server.
// Anything that is not a screen URL is forwarded there.
const target = new URL(process.env.CHECKER_URL || "http://127.0.0.1:8000");
const FORWARD = /^\/(api\/|img\/|a\/\d+\/(upload|grades\.csv|export\.csv)$|s\/\d+\/pdf$|m\/\d+\/overlay\.png$)/;

config.server = {
  ...config.server,
  enhanceMiddleware: (middleware) => (req, res, next) => {
    if (!FORWARD.test(req.url.split("?")[0])) return middleware(req, res, next);
    const proxied = http.request(
      { host: target.hostname, port: target.port, path: req.url, method: req.method, headers: { ...req.headers, host: target.host } },
      (r) => {
        res.writeHead(r.statusCode, r.headers);
        r.pipe(res);
      },
    );
    proxied.on("error", () => {
      res.statusCode = 502;
      res.end(`The Python server is not reachable at ${target.origin}. Start it with: uv run python -m checker.cli serve`);
    });
    req.pipe(proxied);
  },
};

module.exports = config;
