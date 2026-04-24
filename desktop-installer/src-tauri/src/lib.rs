pub mod errors;
pub mod manifest;
pub mod payload;
pub mod installer;
// TODO: cross-session — Session B added these modules. Other sessions may need to coordinate.
pub mod download;
pub mod cleanup;
pub mod install_manifest;
// Session I (PR #50 funnel port): PostHog install-funnel telemetry for the
// LIVE Tauri wizard. Closes the #56 tree-audit gap where the 13 PostHog
// events lived on the post-install welcome page and therefore never fired
// for users who dropped off mid-wizard.
pub mod telemetry;
