// Load browser_extension/config.js, or a copy the app's download set to
// another site (argv[3]), and report what the extension decides with it.
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const [root, file = path.join(root, "browser_extension", "config.js")] = process.argv.slice(2);
const context = vm.createContext({ URL });
vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: "config.js" });
const app = context.BuddyApp;
const pages = ["http://127.0.0.1:8765/", "http://localhost:8765/", "http://127.0.0.1:9000/",
  "https://buddy.example.app/", "https://other.example/"];
console.log(JSON.stringify({
  url: app.url, local: app.local, owns: pages.filter((href) => app.owns(new URL(href))),
}));
