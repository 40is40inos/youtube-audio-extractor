#!/bin/bash

# Ensure a dedicated output folder exists
mkdir -p Downloads

while true; do
    # Clear the screen at the start of each loop for a clean workspace
    clear
    echo "================================================="
    echo "    YOUTUBE HIGH-FIDELITY AUDIO EXTRACTION       "
    echo "    Type 'exit' and press Enter to quit          "
    echo "================================================="
    echo ""

    # Prompt you to paste the URL
    read -p "Paste your YouTube link here: " yt_link

    # Check if you want to quit the script
    if [ "$yt_link" = "exit" ] || [ "$yt_link" = "EXIT" ]; then
        echo ""
        echo "Exiting tool. Goodbye!"
        echo "================================================="
        sleep 1
        clear
        break
    fi

    # Skip empty lines if you accidently hit Enter without pasting
    if [ -z "$yt_link" ]; then
        continue
    fi

    echo ""
    echo "Processing download to the 'YoutubeExtracts' folder..."
    echo ""

    # Run the extraction tool
    ./yt-dlp.exe -f bestaudio --extract-audio --audio-format opus --cookies youtube_cookies.txt -o "YoutubeExtracts/%(title)s.%(ext)s" "$yt_link"

    echo ""
    echo "Done! Track saved inside: YoutubeExtracts/"
    echo ""
    sleep 1.5
done
