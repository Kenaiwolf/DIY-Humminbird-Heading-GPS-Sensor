# DIY Heading and GPS Receiver for Humminbird Sonars

This project provides an open-source solution for interfacing custom GPS and heading sensors with Humminbird sonar units (specifically the Helix series). The goal is to provide a modern, affordable, and DIY-friendly alternative to factory-supplied hardware by emulating the proprietary NMEA 0183 protocol required by Humminbird devices.

## Overview
Many Humminbird units require specific proprietary NMEA sentences to unlock heading/compass functionality. This project documents the communication protocol and provides the firmware logic to enable these features using low-cost, readily available hardware components.

## Support the Project
If this project helped you save money or improved your boat's navigation, please consider supporting the ongoing development. Your contributions help cover hardware costs and the time spent refining the protocol.
[![Sponsor] placeholder
[![Buy Me a Coffee] placeholder

Donations go toward purchasing new testing hardware and covering hosting fees

## Data & Protocol Documentation
The communication protocol relies on proprietary `$PTSI` NMEA 0183 sentences. Below are the verified logs and data structures required for the head unit to recognize the sensor.

### Hardware Handshake
* `$PTSI153,5*30` - Identification sequence.
* `$PTSI150,3*35` - Identification sequence.

### Heading Data
* `$PTSI160,v1,v2,HEADING*CHECKSUM` - Primary heading output.

*Note: Detailed communication logs and binary captures can be found in the `/data` folder of this repository.*

## Getting Started
1. **Hardware:** [Insert list of your components, e.g., ESP32, Compass Module]
2. **Wiring:** [Insert wiring diagram or link to schematic]
3. **Firmware:** Download the source code, configure your serial pins, and flash your microcontroller.

## Contributing
This is a community-driven project. If you have captured logs from different Humminbird models or wish to optimize the protocol implementation, please submit a Pull Request.

## Disclaimer
This project is an independent DIY initiative. It is not affiliated with, endorsed by, or sponsored by Humminbird. Use this interface at your own risk.



