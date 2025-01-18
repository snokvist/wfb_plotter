#!/bin/bash

sudo systemctl $1 wfb-cluster-manager@gs.service
sleep 3
sudo systemctl status wfb-cluster-manager@gs.service

# Always keep a small sleep before exit
sleep 0.5
exit 0
