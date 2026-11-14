"""Generate the app's typographic mark using the Windows installed font."""
from pathlib import Path
import os
from PIL import Image,ImageDraw,ImageFont

root=Path(__file__).resolve().parent.parent
out=root/'assets';out.mkdir(exist_ok=True)
image=Image.new('RGBA',(256,256),(0,0,0,0))
draw=ImageDraw.Draw(image)
draw.rounded_rectangle((0,0,255,255),radius=48,fill='#142E35')
font=ImageFont.truetype(str(Path(os.environ['WINDIR'])/'Fonts'/'segoeuib.ttf'),144)
draw.text((43,18),'S',fill='#7EE0C4',font=font)
draw.line((171,191,207,66),fill='#7EE0C4',width=12)
image.save(out/'app.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])

# Navigation uses the licensed SVG sources in assets/; no installed icon font is needed.
