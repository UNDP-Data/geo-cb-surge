#!/bin/bash

USERNAME=$1
PASSWORD=$2
GROUPNAME=cbsurge

# skip if user already exists
if id "$USERNAME" &>/dev/null; then
    echo "User $USERNAME already exists."
else
    # create new user
    useradd -m -s /bin/bash "$USERNAME"
    echo "$USERNAME:$PASSWORD" | chpasswd
    echo "User $USERNAME created."

    # Add the user to the group
    usermod -aG $GROUPNAME "$USERNAME"
    echo "User $USERNAME added to $GROUPNAME group."

    # Grant sudo access (optional)
    usermod -aG sudo "$USERNAME"
    echo "User $USERNAME granted sudo privileges."
fi

# Set ownership of /app folder to the user
chown -R "$USERNAME:$USERNAME" /app
echo "Ownership of /app granted to $USERNAME."