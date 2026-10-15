// No model/provider configuration: Pi uses the VM's existing approved setup.
import { spawnSync } from "node:child_process";
import { join } from "node:path";

export default function (pi) {
  const report = (action, reason) => {
    if (!process.env.BOX_SESSION) return;
    const result = spawnSync(join(process.env.HOME, ".box/hook.sh"),
      [action, ...(reason ? [reason] : [])], { input: "", timeout: 5000 });
    if (result.error || result.status !== 0) {
      process.stderr.write("kuggis: could not record Pi session status\n");
    }
  };
  pi.on("session_start", async () => report("idle"));
  pi.on("input", async (event) => {
    // Extension-generated continuation is not an answer from the user.
    if (event.source !== "extension") report("prompt");
  });
  pi.on("agent_start", async () => report("working"));
  pi.on("tool_execution_end", async () => report("working"));
  pi.on("agent_settled", async () => report("idle"));
  // A permission/question extension can signal its dialog without sending text.
  pi.events.on("kuggis:needs-you", (event) => {
    if (["question", "permission", "blocked", "done"].includes(event?.why)) {
      report("waiting", event.why);
    }
  });
  pi.on("session_shutdown", async () => report("stopped"));
}
