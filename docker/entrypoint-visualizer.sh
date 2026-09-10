#!/bin/sh
# Waits for the evolve service to write its first checkpoint, then starts the
# visualizer against it. See docker-compose.yml.
until [ -d /project/openevolve_output/checkpoints ]; do
    echo "Waiting for checkpoints directory to be created..."
    sleep 5
done

echo "Checkpoints directory found! Starting visualizer..."
exec python /app/scripts/visualizer.py --path /project/openevolve_output/checkpoints --host 0.0.0.0
