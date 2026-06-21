Here is the updated README.md containing all the exact typography parameters used in the application. Adding this information directly to your repository is highly beneficial, as it provides clarity for developers who want to modify the UI layout or scale the scanning dimensions safely.

ARK: Survival Ascended – Automation Bot
An automated log monitoring and tribal status tracking utility designed for ARK: Survival Ascended. The bot runs as a lightweight desktop background worker, captures specific game screen regions using high-performance pixel diffing, analyzes text utilizing advanced OCR error-correcting algorithms, and relays critical gameplay notifications instantly to your Discord server via Webhooks.

🚀 Key Features
High-Speed Screen Capture: Uses mss for ultra-fast screenshotting and lightweight native numpy evaluations to ensure low performance overhead while playing.

Dual-Layer Alert Detection:

Primary System: Direct color matrix evaluation specifically listening for red warning text typical of dangerous game actions.

Secondary System: Optical Character Recognition (OCR) fallback processing.

Typo-Tolerant OCR: Customized regular expression filters engineered to seamlessly resolve classic Tesseract or transcription errors (such as translating killed into kiIIed, kl1led, or destroyed into d3str0yed).

Independent Tribe Roster Monitoring: Separately tracks online counts (e.g., 2/6) to send instant Join/Leave notifications to Discord without requiring log activity.

Fine-Grained Filtering: Toggleable ignore switches block redundant Discord alerts for non-critical activities (e.g., Taming, Claims, Demolitions, Freezes, or Tribe Membership changes).

Discord Integration: Rich embedded Discord layouts accompanied by customizable automated Role Pings (using direct Role IDs).

User-Friendly UI Overlay: Modern Dark-Themed GUI built using CustomTkinter featuring a Snipping-Tool-style drag-and-drop region layout interface.

🎨 Interface Typography & Theme Specification
If you plan on modifying the design system or scaling the interface windows, the visual layout maps across the following exact typography constants defined within ark_bot.py[cite: 1]:

Font Configuration Mapping
Font Type Class	Target Font Family	Pixel Size	Weight / Style	Application Mapping
FONT_TITLE[cite: 1]	Segoe UI[cite: 1]	13[cite: 1]	Bold ("bold")[cite: 1]	Section Header Labels, Control Buttons[cite: 1]
FONT_LABEL[cite: 1]	Segoe UI[cite: 1]	11[cite: 1]	Regular[cite: 1]	Input Boxes, Checkbox Text, standard labels[cite: 1]
FONT_SMALL[cite: 1]	Segoe UI[cite: 1]	9[cite: 1]	Regular[cite: 1]	Subtitles, Path references, Status strings[cite: 1]
FONT_MONO[cite: 1]	Consolas[cite: 1]	10[cite: 1]	Regular[cite: 1]	Live Diagnostic Log Box, Hotkey display fields[cite: 1]
Note: Special UI text blocks such as the Primary branding banner utilize hardcoded adjustments ("Segoe UI Black", size 16) to maintain clean relative visual scale across the application layout[cite: 1].

⚙️ Running as a Standalone .exe
When running this bot as a compiled .exe, all Python code, UI assets, and libraries are packed tightly inside the file. However, the Windows machine running the .exe still needs Tesseract OCR installed.

The application code inside ark_bot.py is optimized to look for standard Tesseract installation directory pathways automatically[cite: 1]:

Setup Checklist for End-Users:
Download and run the Tesseract installer from the UB-Mannheim Tesseract Wiki.

Leave the installation location as default (C:\Program Files\Tesseract-OCR).

Run ark_bot.exe. The bot will automatically bridge the gap to the local Tesseract installation without any configuration.

📖 Configuration Guide
1. Webhook Setup
Open the bot panel and select 🔗 Set Discord Webhook.

Paste your Discord Channel Webhook URL and hit Save.

2. Scanning Regions Configuration
For optimal reading performance, you must accurately define your screen scanning layouts via the ▣ Configure Areas button:

Alert Area: Map this selection directly over the upper region where red warning kill/destroy notification flags show up on-screen.

Online Counter: Crop this area tightly around the online tribe player fractions display grid (e.g., X/Y).

3. Configuring Role Pings
⚠️ Important Notification Regarding Pings: Discord does not broadcast alerts if you supply a plain text role name (e.g., TribeAlpha). You must provide the actual numeric Discord Role ID.

To acquire a Role ID: Enable Developer Settings on Discord, navigate to Server Settings -> Roles, right-click the desired target role, and select Copy Role ID.

Paste the numeric value inside Configure Pings. Leaving this option empty defaults automatically to broadcasting an @everyone alert.

🎛️ Keyboard Configuration Controls
Global Default Start/Stop Toggle: F5

Change your execution bindings by clicking the settings gear button (⚙) positioned directly adjacent to the control block inside the application panel window.

🧑‍💻 Architecture Details
The program operates inside an isolated tracking loop running parallel operational worker pipelines to prevent freezing your thread context:

                  [ Game Windows Monitor (ArkAscended) ]
                                    │
                  ┌─────────────────┴─────────────────┐
                  ▼                                   ▼
          [ Region 1: Alerts ]              [ Region 2: Counters ]
                  │                                   │
       (Pixel Diff & Red Filter)               (Ocr Digits Pass)
                  │                                   │
      (OCR Keyword Validation)                        │
                  │                                   │
                  └─────────────────┬─────────────────┘
                                    ▼
                      [ Discord Embed Webhook Pipeline ]
📝 License
Distributed under the MIT License. See LICENSE for more information.

Disclaimer: This automation software script functions purely as an external visual overlay scanner. Review third-party software rules provided by Studio Wildcard before using.
