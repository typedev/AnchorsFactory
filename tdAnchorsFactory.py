from fontParts.world import OpenFont, RFont, RGlyph
import math
import os
import logging
from datetime import datetime
import argparse

# TODO: add rule to calculate x position by top and bottom extremums (for circular glyphs, eg. o e c, etc.)
# TODO: add rule to calculate x position by two top and bottom points (for accents, eg. grave, acute, etc.)

class TDAnchorsFactory:
	def __init__(self, UFOfile='', AnchorsRulesFile='anchors-list.txt', clear_exist_anchors=True, 
                 replace_anchors=True, saveOutputUFOfile=False, saveExistingAnchors=False, 
                 log_directory='logs'):
		self.clear_exist_anchors = clear_exist_anchors
		self.replace_anchors = replace_anchors
		self.UFOfile = UFOfile
		self.UFOfile_anchored = '_anchored.ufo'
		self.AnchorsRulesFile = AnchorsRulesFile
		self.saveOutputUFOfile = saveOutputUFOfile
		self.saveExistingAnchors = saveExistingAnchors
		
		# Инициализация логгера при создании объекта
		font_name = os.path.basename(UFOfile).split('.')[0] if UFOfile else 'default'
		self.logger = self.setup_logger(
			log_directory=log_directory,
			font_name=font_name,
			font_style='regular'  # можно добавить определение стиля шрифта
		)

	def _has_anchor(self, glyph: RGlyph):
		if len(glyph.anchors) > 0:
			return True
		else:
			return False

	def _has_anchor_name(self, glyph: RGlyph, anchor_name: str):
		for anchor in glyph.anchors:
			if anchor_name == anchor.name:
				return True
		return False

	def _get_anchor_position(self, glyph: RGlyph, anchor_name: str):
		if self._has_anchor(glyph):
			for anchor in glyph.anchors:
				if anchor_name == anchor.name:
					return (anchor.x, anchor.y)

	def _remove_all_anchors(self, glyph: RGlyph):
		if self._has_anchor(glyph):
			for anchor in glyph.anchors:
				glyph.removeAnchor(anchor)

	def _remove_anchor(self, glyph: RGlyph, anchor_name: str = 'clear'):
		if self._has_anchor(glyph):
			for anchor in glyph.anchors:
				if anchor_name == 'clear':
					glyph.removeAnchor(anchor)
				elif anchor_name == anchor.name:
					glyph.removeAnchor(anchor)

	def _copy_anchors(self, source_glyph: RGlyph, target_glyph: RGlyph, anchors_list: list = None, overwrite: bool = True):
		if not anchors_list:
			for anchor in source_glyph.anchors:
				if overwrite:
					self._remove_anchor(target_glyph, anchor.name)
				target_glyph.appendAnchor(anchor.name, (anchor.x, anchor.y))
		else:
			for anchorname in anchors_list:
				for anchor in source_glyph.anchors:
					if anchor.name == anchorname:
						if overwrite:
							self._remove_anchor(target_glyph, anchorname)
						target_glyph.appendAnchor(anchor.name, (anchor.x, anchor.y))

	def _move_anchor(self, glyph: RGlyph, anchor_name: str, offset: tuple = (0, 0)):
		for anchor in glyph.anchors:
			if anchor.name == anchor_name:
				anchor.move(offset)

	def _get_save_filename(self, font: RFont) -> str:
		"""
		Generate filename for saving anchors with timestamp
		"""
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
		base_name = os.path.splitext(os.path.basename(font.path))[0]
		return f"{base_name}_anchors_{timestamp}.txt"

	def _clean_line(self, text):
		text = text.lstrip()
		text = text.rstrip()
		text = text.replace(' ', '')
		return text

	def _parse_anchors_rules(self, text: str):
		labels = {}
		glyphs = {}
		sfxlist = ['']
		shiftX = 0
		for line in text:
			line = self._clean_line(line)
			if line and not line.startswith('#'):
				if line.startswith('@'):
					namelabel = line.split('=')[0]
					content = line.split('=')[1]
					if namelabel == '@SFXLIST':
						for sfx in content.split(','):
							self.logger.info(f"Found suffix: {sfx}")
							sfxlist.append('.'+sfx)
						self.logger.info(f"Complete suffix list: {sfxlist}")
					elif namelabel == '@SHIFTX':
						shiftX = int(content)
					else:
						labels[namelabel] = content
				else:
					glyphname = line.split('=')[0]
					content = line.split('=')[1]
					glyphs[glyphname] = content
		return labels, glyphs, sfxlist, shiftX

	def _process_anchor_labels(self, labels: dict, glyph_list: dict):
		strukt = {}
		for glyphname, content in glyph_list.items():
			contentlist = content.split(',')
			complielist = []
			for line in contentlist:
				if line.startswith('@'):
					try:
						line = labels[line]
					except (KeyError, AttributeError):
						self.logger.error(f'Label {line} not found * {glyphname}={content} *')
						line = None
				complielist.append(line)
			if None not in complielist:
				strukt[glyphname] = ','.join(complielist)
		return strukt

	def _calculate_italic_shift(self, font: RFont, y_pos: int):
		italics_shift = 0
		angle = font.info.italicAngle
		if angle:
			italics_shift = y_pos * math.tan(-angle * 0.0175)
		return italics_shift

	def _get_right_margin_at_height(self, glyph: RGlyph, y_pos: int):
		try:
			(xMin, yMin, xMax, yMax) = glyph.bounds
		except (AttributeError, TypeError):  # Catch specific exceptions when glyph.bounds is invalid
			self.logger.warning(f'Invalid bounds for glyph {glyph.name}. Using default values for right margin.')
			xMin = 0
			xMax = 0
		xMax = int(round(xMax,0))
		xMin = int(round(xMin,0))
		for x in range(xMax+10,xMin-10,-1):
			if glyph.pointInside((x, y_pos)):
				return x
		return xMax

	def _get_left_margin_at_height(self, glyph: RGlyph, y_pos: int):
		try:
			(xMin, yMin, xMax, yMax) = glyph.bounds
		except (AttributeError, TypeError):  # Catch specific exceptions when glyph.bounds is invalid
			self.logger.warning(f'Invalid bounds for glyph {glyph.name}. Using default values for left margin.')
			xMin = 0
			xMax = 0
		xMax = int(round(xMax, 0))
		xMin = int(round(xMin, 0))
		for x in range(xMin-10,xMax+10):
			if glyph.pointInside((x, y_pos)):
				return x
		return xMin

	def _calculate_anchor_position(self, font: RFont, glyph: RGlyph, align: str, y_pos: int):
		try:
			(xMin, yMin, xMax, yMax) = glyph.bounds
		except (AttributeError, TypeError):  # Catch specific exceptions when glyph.bounds is invalid
			self.logger.warning(f'Invalid bounds for glyph {glyph.name}. Using default values.')
			xMin = 0
			xMax = 0
		if align == 'center':
			return glyph.width/2 + self._calculate_italic_shift(font, y_pos)
		elif align == 'left':
			if y_pos != 0:
				return xMin + self._calculate_italic_shift(font, y_pos)
			else:
				return xMin
		elif align == 'right':
			if y_pos != 0:
				return xMax + self._calculate_italic_shift(font, y_pos)
			else:
				return xMax
		elif align == 'leftinter':
			xMin = self._get_left_margin_at_height(glyph, y_pos)
			return xMin
		elif align == 'rightinter':
			xMax = self._get_right_margin_at_height(glyph, y_pos)
			return xMax
		elif align == 'centerpos':
			try:
				x1,y1,x2,y2 = glyph.bounds
				return (x2-x1)/2 + x1
			except (AttributeError, TypeError):
				self.logger.warning(f'Invalid bounds for centerpos calculation in glyph {glyph.name}. Using default value.')
				return 0
		else:
			try:
				x = int(align)
			except (ValueError, TypeError):
				self.logger.error(f'Cannot recognize align value for {glyph.name}: {align}, {y_pos}')
				x = 0
			return x

	def set_glyph_anchor(self, font: RFont, glyph_name: str, code: str, suffix_list: list, shift_x: int = 0):
		if glyph_name not in font:
			self.logger.warning(f'Glyph not found: {glyph_name}={code}')
			return

		for sfx in suffix_list:
			if sfx:
				self.logger.info(f'Processing suffix: {sfx}')
			glyphname_ = glyph_name + sfx
			if glyphname_ in font:
				self.logger.info(f'Processing glyph: {glyphname_}')
				glyph = font[glyphname_]
				if self.clear_exist_anchors:
					self._remove_all_anchors(glyph)
				for anchor_code in code.split(','):
					try:
						anchorname = anchor_code.split(":")[0]
						align = anchor_code.split(":")[1]
						Ypos = anchor_code.split(":")[2]
					except IndexError:  # Catch specific exception when split doesn't have enough elements
						self.logger.error('ERROR 0 !!! Invalid anchor code:\n\t%s=%s' % (glyphname_, anchor_code))
					
					if Ypos.startswith('$'):
						Ypos = Ypos.replace('$','')
						if '*' not in Ypos: # possible Ypos is a reference to another glyph
							if not Ypos.endswith('_') and Ypos in font:
								try:
									(xMin, yMin, xMax, Ypos) = font[Ypos].bounds
								except (KeyError, AttributeError):  # Catch missing glyph or invalid bounds
									self.logger.error('ERROR 1 !!! Reference glyph not found:\n\t%s=%s' % (glyphname_, code))
									Ypos = 0
									
							elif Ypos.endswith('_'):
								Ypos = ''.join(Ypos[:-1])
								if Ypos in font:
									try:
										(xMin, yMin, xMax, Ypos) = font[Ypos].bounds
										Ypos = yMin
									except (AttributeError, NameError):  # Catch errors when yMin is not accessible
										self.logger.error('ERROR 2 !!! Reference glyph not found:\n\t%s=%s' % (glyphname_, code))
										Ypos = 0
										
								else:
									self.logger.error('ERROR 3 !!! Reference glyph not found:\n\t%s=%s' % (glyphname_, code))
									Ypos = 0

						else:
							baseg = Ypos.split('*')[0]
							shiftY = Ypos.split('*')[1]
							if baseg in font:
								try:
									(xMin, yMin, xMax, Ypos) = font[baseg].bounds
								except (KeyError, AttributeError):  # Catch missing glyph or invalid bounds
									self.logger.error ('ERROR 4 !!! Reference glyph not found:\n\t%s=%s' % ( glyphname_, code ))
									Ypos = 0
									yMin = 0
								if '/' in shiftY:
									d1 = int(shiftY.split('/')[0])
									d2 = int(shiftY.split('/')[1])
									Ypos = ((Ypos - yMin) / d2) * d1
								else:
									Ypos = 0
							else:
								Ypos = 0
					else:
						Ypos = int(Ypos)
					if self.replace_anchors and self._has_anchor_name(glyph, anchorname):
						self._remove_anchor(glyph, anchorname)
					x = self._calculate_anchor_position(font, glyph, align, Ypos)
					glyph.appendAnchor(anchorname, (x+shift_x,Ypos))

	def load_anchors_from_file(self, font: RFont, filepath: str = None):
		if not filepath:
			fn = font.fileName + '.anchors_list.txt'
		else:
			fn = filepath
		if os.path.exists(fn):
			self.logger.info('='*60)
			self.logger.info(f'{font.info.familyName} {font.info.styleName}')
			self.logger.info('Loading anchors list from file:')
			self.logger.info(fn)
			f = open(fn, mode = 'r')
			listofanchors = []
			for line in f:
				line = line.strip()
				listofanchors.append(line)
			f.close()
			return listofanchors
		else:
			self.logger.error(f'Anchor construction file not found: {fn}')
			return None

	def save_anchors_to_file(self, font: RFont):
		self.logger.info('='*60)
		self.logger.info(f'{font.info.familyName} {font.info.styleName}')
		self.logger.info('Saving anchors list to file:')
		fn = self._get_save_filename(font)
		self.logger.info(fn)
		listofanchors = []
		for glyph in font:
			if glyph.anchors:
				anchorlist = '%s=' % glyph.name
				for anchor in glyph.anchors:
					anchorlist += '%s:%i:%i,' % (anchor.name, int(anchor.x), int(anchor.y))
				listofanchors.append(anchorlist[:-1])
		anchfile = open(fn, mode = 'w')
		anchtxt = '\n'.join(listofanchors)
		anchfile.write(anchtxt)
		anchfile.close()
		self.logger.info('File saved successfully.')

	def apply_anchors(self, font: RFont, anchors_code_list: list):
		labels, glyphs, sfxlist, shiftX = self._parse_anchors_rules(anchors_code_list)
		for glyphname, code in self._process_anchor_labels(labels, glyphs).items():
			self.set_glyph_anchor(font, glyph_name = glyphname, code = code, suffix_list = sfxlist, shift_x = shiftX)

	def process_anchors_from_file(self, font: RFont, save_existing: bool = True, anchors_file_path: str = None):
		if save_existing:
			self.save_anchors_to_file(font)
		anchorsListConstruction = self.load_anchors_from_file(font, anchors_file_path)
		self.apply_anchors(font, anchorsListConstruction)

	def setup_logger(self, log_directory: str, font_name: str, font_style: str):
		"""Basic logger setup"""
		os.makedirs(log_directory, exist_ok=True)
		
		timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
		log_filename = f"{timestamp}_{font_name}_{font_style}_anchors.log"
		log_path = os.path.join(log_directory, log_filename)
		
		logging.basicConfig(
			level=logging.INFO,
			format='%(asctime)s - %(levelname)s - %(message)s',
			handlers=[
				logging.FileHandler(log_path, encoding='utf-8'),
				logging.StreamHandler()
			]
		)
		return logging.getLogger(__name__)

	def run(self):
		if self.UFOfile:
			try:
				font = OpenFont(self.UFOfile)
				self.logger.info(f'Processing font: {self.UFOfile}')
				
				self.process_anchors_from_file(
					font, 
					save_existing=self.saveExistingAnchors, 
					anchors_file_path=self.AnchorsRulesFile
				)
				
				if self.saveOutputUFOfile:
					output_path = font.path.replace('.ufo', self.UFOfile_anchored)
					font.save(output_path)
					self.logger.info(f'Saved anchored font to: {output_path}')
			except Exception as e:
				self.logger.error(f'Error processing font: {str(e)}')
				raise
		else:
			self.logger.error("No UFO file specified")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Process UFO files and add anchors.')
	parser.add_argument('--ufo', type=str, help='Path to UFO file', default='test/test-font.ufo')
	parser.add_argument('--rules', type=str, help='Path to anchors rules file', default='anchors-list.txt')
	parser.add_argument('--clear-anchors', action='store_true', help='Clear existing anchors')
	parser.add_argument('--replace-anchors', action='store_true', help='Replace existing anchors')
	parser.add_argument('--save-output', action='store_true', help='Save output UFO file')
	parser.add_argument('--save-existing', action='store_true', help='Save existing anchors')
	parser.add_argument('--log-dir', type=str, help='Log directory', default='logs')

	args = parser.parse_args()

	factory = TDAnchorsFactory(
		UFOfile=args.ufo,
		AnchorsRulesFile=args.rules,
		clear_exist_anchors=args.clear_anchors,
		replace_anchors=args.replace_anchors,
		saveOutputUFOfile=args.save_output,
		saveExistingAnchors=args.save_existing,
		log_directory=args.log_dir
	)
	factory.run()

