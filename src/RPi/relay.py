"""Module controlling relay using remote connection."""

import asyncio
import websockets
import json
import gpiod

# Server URLs
BASE_URL = "https://edlserver-production.up.railway.app"

import RPi.GPIO as GPIO


GPIO.setmode(GPIO.BCM)


GPIO.setup(17, GPIO.OUT)


phase_gpio = {"A": 17, "C": 17, "R": 17, "Y": 17, "B": 17}


def test_gpio():
    GPIO.output(17, GPIO.HIGH)


def gpi_set(phase, command):
    """Set GPIO pins based on phase"""

    if phase in phase_gpio:
        print("LOLA")
        if command.strip().upper() == "ON":
            GPIO.output(phase_gpio[phase], GPIO.HIGH)
        elif command.upper().strip() == "OFF":
            GPIO.output(phase_gpio[phase], GPIO.LOW)
        else:
            print("Wrong Command: ", command)
    else:
        print("Wrong Phase")
        pass


def gpi_status(phase):
    """Get GPIO status based on phase"""
    if phase in phase_gpio:
        status = GPIO.input(phase_gpio[phase])
        return "on" if status == GPIO.HIGH else "off"
    else:
        print("Wrong Phase")
        return None


async def websocket_client():
    uri = "wss://edlserver-production-b9fa.up.railway.app/ws"

    status = {
        "R": gpi_status("R"),
        "B": gpi_status("B"),
        "Y": gpi_status("Y"),
    }

    async with websockets.connect(uri) as websocket:
        connect_msg = json.dumps(
            {"type": "connect", "device_id": "random12"}
        )  # TODO: Make device_id dynamic
        await websocket.send(connect_msg)
        print("[INFO]: Connected to server")

        async def send_status_updates():
            while True:
                await asyncio.sleep(10)
                status_msg = {
                    "status": {
                        "R": gpi_status("A"),
                        "Y": gpi_status("R"),
                        "B": gpi_status("R"),
                    }
                }
                await websocket.send(json.dumps(status_msg))
                print(f"Sent status: {status_msg}")

        asyncio.create_task(send_status_updates())

        while True:
            try:
                response = await websocket.recv()  # Wait for message from server
                response = json.loads(response)  # Decode JSON

                if response.get("type") == "command":
                    command = response["command"]
                    print(f"Server response: {response}")

                    if command == "on" or command == "off":
                        phase = response["phase"].upper()
                        print(f"Phase: {phase}")
                        gpi_set(phase, command)
                        print(f"Phase Turned {command.upper()}: {phase}")

                    elif command == "status":
                        data = {}
                        for phase_ in phase_gpio:
                            data[phase_] = gpi_status(phase_)
                            print(f"Status of Phase {phase_}: {data[phase_]}")
                        res = {"status": data}
                        await websocket.send(json.dumps(res))
                        print("Status sent to server")

            except KeyboardInterrupt:
                print("Disconnected by user")
                break
            except Exception as e:
                print(f"Error: {e}")
                break


if __name__ == "__main__":
    asyncio.run(websocket_client())
