import board
import busio
import digitalio
from adafruit_rgb_display import st7789
from adafruit_rgb_display.rgb import color565
from adafruit_bus_device.spi_device import SPIDevice



 cs_pin = None
 dc_pin = digitalio.DigitalInOut(board.D24)
 reset_pin = digitalio.DigitalInOut(board.D25)

freq = 8000000



spi = busio.SPI(board.SCK, MOSI=board.MOSI)
device = SPIDevice(spi,baudrate=freq,polarity=1,phase=0)

 display = st7789.ST7789(spi,cs=cs_pin,dc=dc_pin,rst=reset_pin,baudrate=freq,width=240,height=240,x_offset=50,y_offset=50,)

display.fill(color565(255, 0, 0))




import board
import displayio
from adafruit_st7789 import ST7789

spi = board.SPI()
while not spi.try_lock():
    pass
spi.configure(baudrate=24000000) # Configure SPI for 24MHz
spi.unlock()
tft_cs = board.D5
tft_dc = board.D6

displayio.release_displays()
display_bus = displayio.FourWire(spi, command=tft_dc, chip_select=tft_cs, reset=board.D9)

display = ST7789(display_bus, width=240, height=240, rowstart=80)

# Make the display context
splash = displayio.Group()
display.show(splash)

color_bitmap = displayio.Bitmap(240, 240, 1)
color_palette = displayio.Palette(1)
color_palette[0] = 0xFF0000

bg_sprite = displayio.TileGrid(color_bitmap,
                               pixel_shader=color_palette,
                               x=0, y=0)
splash.append(bg_sprite)

while True:
    pass