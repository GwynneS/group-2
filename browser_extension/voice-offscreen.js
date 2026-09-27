const voiceApi = globalThis.browser ?? globalThis.chrome;
voiceApi.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.target !== "buddy-audio" || sender.id !== voiceApi.runtime.id) return;
  if (message.type === "stop") {
    respond(BuddyAudio.stop());
  } else if (message.type === "play") {
    BuddyAudio.play(message).then(respond, error => respond({ played: false, error: String(error) }));
    return true;
  }
});
