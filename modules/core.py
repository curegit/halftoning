from sys import float_info
from math import floor, ceil, sqrt, sin, cos, acos, pi
from itertools import product
from PIL import Image, ImageFilter, ImageOps
from cairo import ImageSurface, Context, Antialias, Filter, FORMAT_ARGB32, OPERATOR_SOURCE

# ドット半径から占有率を返す関数を返す
def make_occupancy(pitch):
	def occupancy(radius):
		if radius < 0:
			return 0.0
		elif radius < pitch / 2:
			return pi * radius ** 2 / pitch ** 2
		elif radius < sqrt(2) / 2 * pitch:
			theta = acos(pitch / (2 * radius))
			return (radius / pitch) ** 2 * (pi - 4 * theta) + 2 * radius * sin(theta) / pitch
		else:
			return 1.0
	return occupancy

# 2分法による求根
def bisection(f, x1, x2, eps):
	while True:
		x = (x1 + x2) / 2
		y = f(x)
		if abs(y) < eps:
			return x
		if f(x1) * y > 0:
			x1 = x
		else:
			x2 = x

# 占有率からドット半径への変換テーブルをつくる
def radius_table(pitch, depth):
	color = 0
	occupancy = 0.0
	while occupancy <= pi / 4:
		yield pitch * sqrt(occupancy / pi)
		color += 1
		occupancy = color / (depth - 1)
	r = pitch / 2
	rmax = sqrt(2) / 2 * pitch
	while color < depth - 1:
		f = make_occupancy(pitch)
		y = lambda x: f(x) - occupancy
		r = bisection(y, r, rmax, float_info.epsilon * 2)
		yield r
		color += 1
		occupancy = color / (depth - 1)
	yield rmax

# 占有率からドット半径を返す関数を返す
def make_radius(pitch, depth):
	table = list(radius_table(pitch, depth))
	def radius(occupancy):
		if occupancy < 0:
			return 0.0
		elif occupancy >= depth:
			return sqrt(2) / 2 * pitch
		else:
			return table[occupancy]
	return radius

# ピクセル空間から網点空間への変換と逆変換をする関数を返す
def make_transforms(pitch, angle, origin=(0.0, 0.0)):
	theta = angle / 180 * pi
	def transform(x, y):
		x -= origin[0]
		y -= origin[1]
		u = (x * cos(theta) - y * sin(theta)) / pitch
		v = (x * sin(theta) + y * cos(theta)) / pitch
		return u, v
	def inverse_transform(u, v):
		x = (u * cos(theta) + v * sin(theta)) * pitch
		y = (v * cos(theta) - u * sin(theta)) * pitch
		x += origin[0]
		y += origin[1]
		return x, y
	return transform, inverse_transform

# シングルバンドの画像から網点の位置と階調のイテレータを返す
def halftone_dots(image, pitch, angle, blur):
	center = image.width / 2, image.height / 2
	transform, inverse_transform = make_transforms(pitch, angle, center)
	xy_bounds = [(-pitch, -pitch), (image.width + pitch, -pitch), (image.width + pitch, image.height + pitch), (-pitch, image.height + pitch)]
	uv_bounds = [transform(*p) for p in xy_bounds]
	lower_u = min([u for u, v in uv_bounds])
	upper_u = max([u for u, v in uv_bounds])
	lower_v = min([v for u, v in uv_bounds])
	upper_v = max([v for u, v in uv_bounds])
	boundary = lambda u, v: lower_u <= u <= upper_u and lower_v <= v <= upper_v
	blurred = image.filter(ImageFilter.GaussianBlur(pitch / 2)) if blur == "gaussian" else (image.filter(ImageFilter.BoxBlur(pitch / 2)) if blur == "box" else image)
	valid_uvs = [p for p in product(range(floor(lower_u), ceil(upper_u) + 1), range(floor(lower_v), ceil(upper_v) + 1)) if boundary(*p)]
	for u, v in valid_uvs:
		x, y = inverse_transform(u, v)
		color = blurred.getpixel((min(max(x, 0), image.width-1), min(max(y, 0), image.height-1)))
		yield x, y, color

# シングルバンドの画像を網点化した画像を返す
def halftone_image(image, pitch, angle, scale, blur=None, keep_flag=False):
	width = round(image.width * scale)
	height = round(image.height * scale)
	if keep_flag:
		return image.resize((width, height), Image.LANCZOS)
	foreground = (1.0, 1.0, 1.0, 1.0)
	background = (0.0, 0.0, 0.0, 1.0)
	radius = make_radius(pitch, 256)
	surface = ImageSurface(FORMAT_ARGB32, width, height)
	context = Context(surface)
	pattern = context.get_source()
	pattern.set_filter(Filter.BEST)
	context.set_antialias(Antialias.GRAY)
	context.set_operator(OPERATOR_SOURCE)
	context.set_source_rgba(*background)
	context.rectangle(0, 0, width, height)
	context.fill()
	context.set_source_rgba(*foreground)
	for x, y, color in halftone_dots(image, pitch, angle, blur):
		r = radius(color) * scale
		context.arc(x * scale, y * scale, r, 0, 2 * pi)
		context.fill()
	return Image.frombuffer("RGBA", (width, height), surface.get_data(), "raw", "RGBA", 0, 1).getchannel("G")

# グレースケールの画像を網点化した画像を返す
def halftone_grayscale_image(image, pitch, angle=45, scale=1.0, blur=None, keep_flag=False):
	inverted = ImageOps.invert(image)
	halftone = halftone_image(inverted, pitch, angle, scale, blur, keep_flag)
	return ImageOps.invert(halftone)

# CMYKの画像を網点化した画像を返す
def halftone_cmyk_image(image, pitch, angles=(15, 75, 30, 45), scale=1.0, blur=None, keep_flags=(False, False, False, False)):
	c, m, y, k = image.split()
	cyan = halftone_image(c, pitch, angles[0], scale, blur, keep_flags[0])
	magenta = halftone_image(m, pitch, angles[1], scale, blur, keep_flags[1])
	yellow = halftone_image(y, pitch, angles[2], scale, blur, keep_flags[2])
	key = halftone_image(k, pitch, angles[3], scale, blur, keep_flags[3])
	return Image.merge("CMYK", [cyan, magenta, yellow, key])

# RGBの画像を網点化した画像を返す
def halftone_rgb_image(image, pitch, angles=(15, 75, 30), scale=1.0, blur=None, keep_flags=(False, False, False)):
	r, g, b = image.split()
	red = halftone_grayscale_image(r, pitch, angles[0], scale, blur, keep_flags[0])
	green = halftone_grayscale_image(g, pitch, angles[1], scale, blur, keep_flags[1])
	blue = halftone_grayscale_image(b, pitch, angles[2], scale, blur, keep_flags[2])
	return Image.merge("RGB", [red, green, blue])