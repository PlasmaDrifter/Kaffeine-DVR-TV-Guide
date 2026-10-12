# Release Notes

## v0.8.6

- **Grid Guide Live Tile Tint Controls**: Renamed the background tint toggle to "Disable" for clear, intuitive toggle state semantics.
- **Settings Layout Optimization**: Repositioned the broadcast category color swatches and secondary guide option controls into adjacent columns, removing excessive whitespace separation.
- **Desktop & Dock Clapperboard Icon Refinement**: Bundled multi-resolution icon assets across XDG and Breeze icon specifications for consistent panel dock, titlebar, and launcher presentation.

## v0.8.5

- **Recording Cancellation & Duplicate Prevention**: Fixed duplicate concurrent recording timers in Kaffeine by introducing active timer pre-checking and thorough multi-target cancellation across D-Bus and SQLite when recordings are stopped or restarted.
- **Default Update Frequency**: Set the default automatic update check interval to weekly.
- **TVPassport Direct Lineup URL**: Updated all TVPassport links in the guide and lineup dialogs to direct to `https://www.tvpassport.com/index.php/lineups` for immediate postal/zip code entry.
- **EPG Grid Recording & Scheduled Indicators**: Differentiated active recording (`● REC` with solid red dot and red border) from scheduled recordings (`○ SCHED` with subtle outline only).
- **EPG List View Enhancements**: Added subtle grid lines (`#2b3242`), removed row index headers, and differentiated scheduled vs active recordings.
- **Release Notes Modal Viewer**: Added an interactive "View Release Notes..." modal dialog with formatted changelog viewer in Settings -> Updates tab and status bar.
- **AppImage Checkmark Rendering**: Bundled checkmark assets and fixed indicator icon resolution in read-only SquashFS AppImage environments.

## v0.8.4

- **List View Navigation & Performance**: Fixed initial auto-scroll so list view immediately jumps to the first live or upcoming program on its first activation, matching subsequent switches.
- **Direct DBus Channel Tuning**: Implemented direct KDBusService CommandLine parameter passing to tune live TV channels cleanly without requiring synthetic keypresses.
- **Recording Indicator Redesign**: Replaced large rectangular badges with clean red dot indicators on EPG grid tiles for a more polished look.
- **Sports Auto-Extend UI**: Aligned the sports buffer duration spinbox with the rest of the form input fields and repositioned the auto-extend toggle to the right.
- **AppImage Distribution & Metadata**: Built and released a standalone x86_64 AppImage with embedded Python and PyQt6 runtimes, complete desktop metadata, and AppManager package compatibility.
- **Background Watcher CLI Dispatching**: Fixed argument dispatch in entrypoint so CLI daemon modes like `--watch` execute headlessly as background services rather than opening a second GUI window.
- **Background Service Auto-Provisioning**: Automated systemd user unit provisioning directly from the AppImage/application with dynamic `ExecStart` path resolution, allowing the background watcher service to enable, start, and run seamlessly without requiring manual install scripts.
- **Documentation & UI Previews**: Refreshed README installation workflows (clarifying standalone AppImage vs. source installation), overview sections, and preview screenshots.
