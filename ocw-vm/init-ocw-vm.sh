#!/bin/bash
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# Install some useful/necessary dependencies to make future installs easier
sudo apt-get update
sudo apt-get install -y make
sudo apt-get install -y libblas-dev
sudo apt-get install -y liblapack-dev
sudo apt-get install -y gfortran
sudo apt-get install -y g++
sudo apt-get install -y build-essential
sudo apt-get install -y python-dev 
sudo apt-get install -y ia32-libs --fix-missing
sudo apt-get install -y git
sudo apt-get install -y vim

# GUI related installs
sudo apt-get install -y lightdm

# XFCE
sudo apt-get install -y xfce4
sudo apt-get install -y xdg-utils
sudo apt-get install -y eog

# Ubuntu Unity
#sudo apt-get install -y ubuntu-desktop

# Use the Easy-OCW Ubuntu install script to get everything
# else installed!
git clone http://git-wip-us.apache.org/repos/asf/climate.git

# Copy the Easy-OCW install script for Ubuntu
cp climate/easy-ocw/install-ubuntu-12_04.sh .
# Copy the requirements files for conda and pip used by Easy-OCW
cp climate/easy-ocw/*.txt .

bash install-ubuntu-12_04.sh -q

# Set symlink for the UI frontend code
cd climate/ocw-ui/backend
ln -s ../frontend/app app

cd