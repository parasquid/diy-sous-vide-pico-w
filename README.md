# DIY Sous Vide using the Pico W and CircuitPython

See the intro video on YouTube:

[<img src="http://i3.ytimg.com/vi/kycNKP-qoUA/hqdefault.jpg" width="100%">](https://www.youtube.com/watch?v=kycNKP-qoUA "The Perfect Steak with the RPI Pico W | DIY Sous Vide")

This project requires a Sonoff flashed with Tasmota (or any wifi enabled device that has a REST API) and an RPi Pico W (an RPi without wireless also works with a wifi coprocessor with some code changes).

You may need to tune your P I and D terms accordingly depending on the ambient teperature and the heating characteristics of your hotpot.

There is a rudimentary recovery built-in to the program such that if it crashes (most often with the DS18B20 having CRC errors) it will try to save the state onto the SD card and reboot the microcontroller, which upon boot will check if there is a state written and will try to reload the latest target temperature and continue from there. Currently there's a bug with the time elapsed where it does not properly recover from it when a reboot happens.

## Schematic

![image_2023-06-20_21-19-29](https://github.com/parasquid/diy-sous-vide-pico-w/assets/185592/24e3df3f-fa76-4944-bccd-9a2fdef39765)

## Pictures

![247196275-338420b1-7770-4ea0-af9b-fd99a0da3249](https://github.com/parasquid/diy-sous-vide-pico-w/assets/185592/ace465a6-dd4f-419a-ba77-f699aeaf767d)
![247196289-5670b796-35c6-4f79-9b70-04cf86ccb7e4](https://github.com/parasquid/diy-sous-vide-pico-w/assets/185592/aa24b114-e60c-4b74-86af-a3652c12347e)
