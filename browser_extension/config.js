// Where the Buddy app (UI/server.py) runs. The app's "Download extension"
// button sends a copy with `url` set to the site it's downloaded from (see
// build_extension_zip in UI/server.py), so an extension downloaded from the
// Vercel site talks to that site. Loaded before the other scripts everywhere.
globalThis.BuddyApp = {
  url: "http://127.0.0.1:8765",

  // A Buddy app on this computer (python3 UI/server.py), rather than a website.
  get local() {
    return ["127.0.0.1", "localhost"].includes(new URL(this.url).hostname);
  },

  // Whether a page is the Buddy app itself. 127.0.0.1 and localhost reach the
  // same local app.
  owns(location) {
    const app = new URL(this.url);
    if (location.origin === app.origin) return true;
    return this.local && ["127.0.0.1", "localhost"].includes(location.hostname)
      && location.protocol === app.protocol && location.port === app.port;
  },
};
