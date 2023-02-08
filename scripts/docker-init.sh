#!/bin/sh -e
set -x

echo y | docker system prune 

if [ -z echo $(docker volume ls -q)]; then docker volume rm $(echo $(docker volume ls -q)); fi