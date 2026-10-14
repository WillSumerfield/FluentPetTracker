# FluentPetTracker

This app pairs with a FluentPet button board to automatically record all the presses your pet makes, and gather metrics about your pet's language trends: which words they use, how often they speak, whether they string words together, and how often they reply when you press something back.

A small camera above the board watches and listens around the clock. Every time a button is pressed, the app works out which word it was and who pressed it, you or your pet. It groups presses into "utterances", saves a short video of each conversation, and builds up figures over weeks and months. When it isn't sure who pressed a button, it asks you to watch the clip and decide.

It all runs at home, on a Raspberry Pi and your own PC, so your video never leaves your own devices. You check in from your phone through Home Assistant, from anywhere, over Tailscale.

## Getting started

### What you need

- A **FluentPet board**, with its buttons recorded (any number of them).
- A **Raspberry Pi Zero 2 W** with 64-bit Raspberry Pi OS, an **Arducam 12MP (IMX708)** camera and a **USB mic**, mounted above the board.
- A **Windows PC** with WSL2 and Docker Desktop (with WSL integration on), and `python3-yaml` in WSL (`sudo apt install python3-yaml`).
- **Tailscale** on the PC and your phone, and the **Home Assistant** app on your phone.
- Somewhere to keep the clips. A folder on a second drive works well.

Give the Pi and the PC fixed addresses on your router (a DHCP reservation), so they don't move around.

### Set up the PC

Everything that's specific to you lives in one file, `config.yml`: your pet's name, the Pi's address, where clips get saved, and so on. Make it from the example the first time:

```
./fluentpet.sh configure
```

Open `config.yml` and go through it. Each setting has a comment saying what it does, and most can stay as they are. At the least, set your pet's name, the Pi's address (`pi.address`) and your PC's address (`pi.allowed_pcs`).

The clips folder needs a marker file in it, so clips are never written to an empty mount point when the drive isn't plugged in:

```
touch /mnt/d/FluentPetTracker/clips/.fluentpet-clips
```

Then start everything:

```
./fluentpet.sh up
```

Run that again whenever you change `config.yml`. It checks your settings first and tells you if anything looks wrong.

### Set up the Pi

`./fluentpet.sh configure` wrote the Pi's settings into `rpi-capture/capture.env`. Copy the whole `rpi-capture/` folder to the Pi and run the installer there:

```
scp -r rpi-capture pi@<pi-address>:
ssh pi@<pi-address> sudo sh rpi-capture/install.sh
```

The Pi now streams around the clock and restarts the stream by itself if it ever stops. Do this again whenever you change the `pi:` settings.

### Set up Home Assistant

1. Open `http://localhost:8123` on the PC and create your account.
2. Add the **MQTT** integration (Settings → Devices & services), with broker `mosquitto` and port `1883`. This is what sends alerts to your phone.
3. Let Home Assistant trust Tailscale. Stop it with `./fluentpet.sh stop homeassistant`, then in `home-assistant/config/.storage/http` set `use_x_forwarded_for` to `true` and `trusted_proxies` to `["127.0.0.1", "172.16.0.0/12"]`. Start it again with `./fluentpet.sh up`.

### Reach it from your phone

Tailscale Serve passes Home Assistant and the app's pages to your tailnet over HTTPS. Nothing is opened to your home network. Run these once on the PC (after `sudo tailscale set --operator=$USER`, so they don't need `sudo`):

```
tailscale serve --bg --https=443  http://127.0.0.1:8123
tailscale serve --bg --https=8443 http://127.0.0.1:8600
tailscale serve --bg --https=8443 --set-path /live/mse/api/ws http://127.0.0.1:5000/live/mse/api/ws
```

Put the address of the second one (`https://<pc>.<tailnet>.ts.net:8443`) in `network.public_address` in `config.yml`, and run `./fluentpet.sh up`. The pages then show up in Home Assistant's sidebar. Open the Home Assistant app on your phone, point it at `https://<pc>.<tailnet>.ts.net`, and you're in.

Windows breaks WSL's network a little every time the PC wakes from sleep, and the phone stops loading anything. Install the fix once:

```
sudo sh wsl/install.sh
```

### Teach it your board's buttons

Before it can tell words apart, the app needs to hear each button once. Open **Enrolment** in the sidebar:

1. Press **Start**, press every button on the board in turn with a second of quiet between them, and press **Stop**. This part works well from your phone.
2. Each press shows up as a highlighted section. Give each one its word, tidy up its edges if needed, and delete any that aren't a button.
3. Press **Save**. The app recognises those words straight away.

You can come back and redo a single word at any time. The others keep theirs.

### Day to day

- **Daily Summary** shows today's presses and conversations, with a clip of each.
- **Clips** lays out every clip from the months you pick, a day to a row, with a bar for each day showing how busy it was. Filter for the ones where your pet spoke, the ones awaiting review, or a particular word, and click one to watch it.
- **Review** lists the presses where the app couldn't tell who pressed. Watch the clip and pick your pet, you, or "nobody" for a false alarm. You can change any press this way, not only those.
- **Metrics** shows the long-term figures.
- **Live Feed** shows the camera. Its **Pause** button switches the camera and mic off at the Pi until you press **Resume**. Paused time doesn't count against the study.
- Your phone gets an alert when your pet says something, or when a new clip is waiting for review.

The study's rules (how long a gap ends a conversation, how quickly a reply has to come, and so on) are in `config.yml` too, and you can change them at any time.

## How it works

The Pi sends one video-and-audio stream to the PC, where four services pick it up, all in Docker:

- **Frigate** watches the video and notes when a person or your pet is standing at the board.
- **Word Detection** listens to the audio and recognises each button by its sound, comparing it with the recordings you made during Enrolment.
- **The Correlator** joins the two by time. A word plus whoever was at the board makes a **Press**. It groups Presses into **Exchanges**, saves a **Clip** of each one, and keeps everything in a SQLite database. It also serves the pages.
- **Home Assistant** shows the pages on your phone and sends the alerts.

They talk to each other over MQTT (Mosquitto), and a small relay passes the Pi's stream to each of them, so the Pi only sends it once over Wi-Fi.

`configure.py` is the only thing that reads `config.yml`. It writes each service's own settings from it, plus Frigate's and Home Assistant's configs from the templates `frigate/config.template.yml` and `home-assistant/configuration.template.yaml`. Those written files aren't committed. Don't edit them by hand; change `config.yml` or the templates instead.

The words in bold have exact meanings. Each part of the project has a `CONTEXT.md` that defines its terms, and `CONTEXT-MAP.md` shows how the parts fit together. Read those if you want the detail, or point an AI agent at them.

## Troubleshooting

**The pages won't load on my phone after the PC has been asleep.**
Windows shrinks WSL's network packet size when it wakes, and Tailscale traffic stops getting through. If you installed the fix (`sudo sh wsl/install.sh`), it puts things right on its own within a second or two. `journalctl -u fluentpet-mtu` shows each time it had to.

**`./fluentpet.sh up` stops and says Frigate's config was changed.**
You probably redrew the Board Zone in Frigate's own settings. That's fine. Copy the coordinates it prints into `frigate.board_zone` in `config.yml` and run `up` again.

**`./fluentpet.sh up` lists problems with my settings.**
It checks every setting before writing anything, and lists all the problems at once. Fix each one in `config.yml` and run it again.

**The Live Feed is black, or nothing is being recorded.**
Check the Pi is on and not Paused (the Live Feed's button says **Resume** if it is). On the Pi, `journalctl -u mediamtx` shows the stream starting and stopping. On the PC, `./fluentpet.sh logs -f word-detection` says "Lost the stream" while it can't reach the Pi.

**Clips from before an upgrade have no picture on the Clips page.**
Clips get their picture as they're cut. Run `./fluentpet.sh thumbnails` once to give older ones theirs.

**Presses are recorded, but there are no clips.**
The clips folder is missing its `.fluentpet-clips` marker, or the drive isn't connected. The app keeps recording presses without clips until it's back.

**Words are missed or mixed up.**
Redo Enrolment for those words, in a quiet room. If it's still off, `word_detection.confident_threshold` and `uncertain_threshold` in `config.yml` set how sure it has to be.

**The wrong person gets the press, or nobody does.**
Check the Board Zone covers the board in Frigate (`http://localhost:5000`). If your pet is seen as a different animal, add that label to `pet.labels`. Either way, the Review page lets you put it right.

**Home Assistant only says "400: Bad Request" through Tailscale.**
Home Assistant doesn't trust Tailscale yet. See step 3 of "Set up Home Assistant".

**Anything else.**
`./fluentpet.sh logs -f <service>` shows a service's log: `correlator`, `correlator-web`, `word-detection`, `frigate` or `homeassistant`.
