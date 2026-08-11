---
title: Xtalate — loss-aware file conversion demo
emoji: ⚛️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 3000
pinned: false
short_description: Public demo of Xtalate, the trusted translation layer between computational chemistry file formats — see exactly what a conversion kept, lost, and assumed.
---

# Xtalate demo

The public, anonymous demo of **[Xtalate](https://github.com/jsong1218/Xtalate)** — a converter
between computational chemistry file formats (XYZ, extXYZ, CIF, POSCAR, CONTCAR, XDATCAR, ASE
trajectories) that tells you exactly what it kept, what it lost, and why. Every conversion produces
a **Conversion Report**: a line-by-line record of each field preserved, dropped because the target
format cannot hold it, or filled by an explicit recovery choice. Nothing is changed silently.

This is a **demo, not a place to store data**:

- Ephemeral — uploads and outputs are deleted after a few hours; nothing is retained.
- 25 MB upload cap.
- Anonymous — no account, no API key.

For larger files, private data, or your own instance, install the CLI or self-host — there is no
size limit when you run it yourself (see the [self-hosting guide](https://github.com/jsong1218/Xtalate/blob/main/docs/self-hosting.md)).
