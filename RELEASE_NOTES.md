# Release Notes

## v0.8.10

- **Channel Importing & Renaming Setup**: Clarified the channel lineup and renaming section in Settings to focus on guide display names (`Guide Name = Tuned Channel`), using `Fox = KSAZ-HD` as an example, with guidance on Welcome Wizard imports and re-importing.
- **TV Passport Station ID Instructions**: Streamlined station setup instructions using `Guide Name = Station ID` (e.g. `NBC = 1812`, `Fox = 1809`, or `PBS = 1184`), eliminating unnecessary technical jargon.
- **Help and Information Tab Synchronization**: Synchronized the Quick Setup Walkthrough in the Help tab with the updated channel importing, renaming, and TV Passport setup formats.

## v0.8.9

- **Guide Auto-Advance Controls**: Added a customizable minute-past-the-hour stepper and enable/disable toggle for guide auto-advance, with an inline help badge explaining next-hour advancement.
- **Three-Way Guide Unhighlighting**: Added toggle-on-click, click-empty-space to deselect, and Escape key clearing across both EPG Grid and List views.
- **Corner Clock Display & Sizing**: Added a live top-right tab bar clock widget with color customization, show/hide toggle, and a dedicated font size stepper in Settings.
- **Settings UI Polish**: Standardized numeric stepper widths to 130 px, changed Live Badge toggle text to "Disable" for consistency, and aligned auto-advance minute calculations across live sync and manual Jump-to-Now actions.

## v0.8.8

- **Grid Options Three-Column Layout**: Reorganized the Grid Guide Options settings card into three balanced columns for cleaner visual hierarchy.
- **Frameless Embedded Steppers**: Modernized numeric stepper controls with a sleek inset container and borderless inline increment/decrement buttons.
- **Setting Label Streamlining**: Refined setting labels to "Grid Rows" and "Grid Box" for concise, uncluttered presentation.
- **Updated Documentation & Previews**: Refreshed README preview screenshots showcasing the three-line EPG grid views and updated settings panel.

## v0.8.7

- **Three-Line Grid Program Tiles**: Redesigned EPG grid program tiles into three dedicated lines for Primary Show Title, Broadcast Time Range, and Episode Title/Subtitle for superior clarity and reduced truncation.
- **Grid Tile Margins & Badge Clearance**: Refined vertical padding to 5 px and inter-line spacing to 2 px, guaranteeing clean clearance for the lower-right LIVE pill badge and top-right recording dot indicator.
- **Grid Row Height Legibility Floor**: Enforced a 58 px minimum row height baseline in grid zoom calculations so program tiles never collapse below readable multi-line bounds during window resizing.
- **Description Box Height Configuration**: Added user-selectable 2-line or 3-line description box height preference in Settings.

## v0.8.6

- **Past Recording History Indicators**: Added past recording cross-referencing so programs completed in history show a distinct badge and completion tooltip in both Grid and List guide views.
- **Guide Toolbar Refresh Button**: Added a dedicated quick-refresh button next to Prime Time to instantly reload guide listings and active recording statuses.
- **Refined Time Jump Alignment**: Aligned grid view hour-slot jumps with the current hour mark until 50 minutes past the hour.
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
