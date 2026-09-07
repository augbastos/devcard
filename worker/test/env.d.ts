// Types for the test environment.
//
// `env` from "cloudflare:test" is typed as `Cloudflare.Env`, which is empty
// until the project says what its bindings are. Pointing it at the Worker's own
// `Env` means a test that reads a binding the Worker does not declare fails to
// compile instead of failing at runtime.
import type { Env as WorkerEnv } from "../src/index";

declare global {
  namespace Cloudflare {
    interface Env extends WorkerEnv {}
  }
}
