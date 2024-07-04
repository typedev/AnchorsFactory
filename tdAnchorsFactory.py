from fontParts.world import *
import math, os


clear_exist_anchors = False
# Clear all existing anchors

replace_anchors = False
# False = If the glyph has an anchor with the same name, save it, but add new ones
# True = Delete with the same name and add a new one

UFOfile = ''
# input UFO file or CurrentFont() - see main() section

UFOfile_anchored = '_anchored.ufo'
# output UFO will be saved as <ufopath>_anchored.ufo
saveOutputUFOfile = True

AnchorsRulesFile = 'anchors-list.txt'
# if the file with the rules is not specified (None), there will be a search by the name of the font file with an addition to the name - .anchors_list.txt
saveExistingAnchors = True


def glyphHasAnchor (glyph):
	if len(glyph.anchors) > 0:
		return True
	else:
		return False


def anchorNameExist (glyph, anchorname):
	for anchor in glyph.anchors:
		if anchorname == anchor.name:
			return True
	return False


def getPosAnchorByName (glyph, anchorname):
	if glyphHasAnchor(glyph):
		for anchor in glyph.anchors:
			if anchorname == anchor.name:
				return (anchor.x, anchor.y)

def removeAnchors (glyph):
	if glyphHasAnchor(glyph):
		for anchor in glyph.anchors:
			glyph.removeAnchor(anchor)


def removeAnchorByName (glyph, anchorname = 'clear'):
	if glyphHasAnchor(glyph):
		for anchor in glyph.anchors:
			if anchorname == 'clear':
				glyph.removeAnchor(anchor)
			elif anchorname == anchor.name:
				glyph.removeAnchor(anchor)


def copyAnchors (sourceglyph, destinationglyph, anchorslist=None, overwrite=True):
	if not anchorslist:
		for anchor in sourceglyph.anchors:
			if overwrite:
				removeAnchorByName(destinationglyph, anchor.name)
			destinationglyph.appendAnchor(anchor.name, (anchor.x, anchor.y))
	else:
		for anchorname in anchorslist:
			for anchor in sourceglyph.anchors:
				if anchor.name == anchorname:
					if overwrite:
						removeAnchorByName(destinationglyph, anchorname)
					destinationglyph.appendAnchor(anchor.name, (anchor.x, anchor.y))

def moveAnchor (glyph, anchorname, offset = (0, 0)):
	for anchor in glyph.anchors:
		if anchor.name == anchorname:
			anchor.move(offset)

####
def getAnchorFileName4Save(font):
	for idx in range(0,1000):
		fn = font.fileName + '.saved_anchors.' + str(idx) + '.txt'
		if not os.path.exists(fn):
			return fn

def stripline (text):
	text = text.lstrip()
	text = text.rstrip()
	text = text.replace(' ', '')
	return text

def parseAnchorsStructure (text):
	labels = {}
	glyphs = {}
	sfxlist = ['']
	shiftX = 0
	for line in text:
		line = stripline(line)
		if line and not line.startswith('#'):
			if line.startswith('@'):
				namelabel = line.split('=')[0]
				content = line.split('=')[1]
				if namelabel == '@SFXLIST':
					for sfx in content.split(','):
						print(sfx)
						sfxlist.append('.'+sfx)
					print (sfxlist)
				elif namelabel == '@SHIFTX':
					shiftX = int(content)
				else:
					labels[namelabel] = content
			else:
				glyphname = line.split('=')[0]
				content = line.split('=')[1]
				glyphs[glyphname] = content
	return labels, glyphs, sfxlist, shiftX


def resortAnchorsStructure (labels, glyphlist):
	strukt = {}
	for glyphname, content in glyphlist.items():
		contentlist = content.split(',')
		complielist = []
		for line in contentlist:
			if line.startswith('@'):
				try:
					line = labels[line]
				except:
					print ('ERROR: Label %s not found * %s=%s *' % (line, glyphname, content))
					line = None
			complielist.append(line)
		if None not in complielist:
			strukt[glyphname] = ','.join(complielist)
	return strukt


def italicShift (font, Ypos):
	italics_shift = 0
	angle = font.info.italicAngle
	if angle:
		italics_shift = Ypos * math.tan(-angle * 0.0175)
	return italics_shift


def getRayRightMargin(glyph, Ypos):
	try:
		(xMin, yMin, xMax, yMax) = glyph.bounds
	except:
		xMin = 0
		xMax = 0
	xMax = int(round(xMax,0))
	xMin = int(round(xMin,0))
	for x in range(xMax+10,xMin-10,-1):
		if glyph.pointInside((x, Ypos)):
			return x
	return xMax

def getRayLeftMargin(glyph, Ypos):
	try:
		(xMin, yMin, xMax, yMax) = glyph.bounds
	except:
		xMin = 0
		xMax = 0
	xMax = int(round(xMax, 0))
	xMin = int(round(xMin, 0))
	for x in range(xMin-10,xMax+10):
		if glyph.pointInside((x, Ypos)):
			return x
	return xMin


def getPosByAlign (font, glyph, align, Ypos):
	try:
		(xMin, yMin, xMax, yMax) = glyph.bounds
	except:
		xMin = 0
		xMax = 0
	if align == 'center':
		return glyph.width/2 + italicShift(font, Ypos)
		# return ((xMax-italicShift(font,Ypos))-xMin)/2 +xMin + italicShift(font,Ypos)
	elif align == 'left':
		if Ypos != 0:
			return xMin + italicShift(font, Ypos)
		else:
			# xMin = getRayLeftMargin(glyph, 0)
			return xMin
	elif align == 'right':
		if Ypos != 0:
			return xMax + italicShift(font, Ypos)
		else:
			# xMax = glyph.width - getRayRightMargin(glyph, 0)
			return xMax
	elif align == 'leftinter':
		xMin = getRayLeftMargin(glyph, Ypos)
		return xMin
	elif align == 'rightinter':
		xMax = getRayRightMargin(glyph, Ypos)
		return xMax
	elif align == 'centerpos':
		x1,y1,x2,y2 = glyph.bounds
		return (x2-x1)/2 + x1
	else:
		try:
			x = int(align)
		except:
			print ('ERROR!!! Something went wrong', glyph.name, align, Ypos)
			x = 0
		return x
	

def setAnchor2Glyph(font, glyphname, code, sfxlist, shiftX=0):
	if glyphname not in font:
		print ('Warning! Glyph not found:\n\t%s=%s' % ( glyphname, code ))
		return

	for sfx in sfxlist:
		# print('Start for SFX', sfx)
		glyphname_ = glyphname + sfx
		if glyphname_ in font:
			# print('\t',glyphname_)
			glyph = font[glyphname_]
			if clear_exist_anchors:
				removeAnchors(glyph)
			for anchor_code in code.split(','):
				
				try:
					anchorname = anchor_code.split(":")[0]
					align = anchor_code.split(":")[1]
					Ypos = anchor_code.split(":")[2]
				except:
					print(
						'ERROR 0 !!! Invalid anchor code:\n\t%s=%s'
						% (glyphname_, anchor_code)
					)
				
				if Ypos.startswith('$'):
					Ypos = Ypos.replace('$','')
					if '*' not in Ypos:
						if not Ypos.endswith('_') and Ypos in font:
							try:
								(xMin, yMin, xMax, Ypos) = font[Ypos].bounds
							except:
								print ('ERROR 1 !!! Reference glyph not found:\n\t%s=%s' % ( glyphname_, code ))
								Ypos = 0
								
						elif Ypos.endswith('_'):
							Ypos = ''.join(Ypos[:-1])
							if Ypos in font:
								try:
									(xMin, yMin, xMax, Ypos) = font[Ypos].bounds
									Ypos = yMin
								except:
									print('ERROR 2 !!! Reference glyph not found:\n\t%s=%s' % (glyphname_, code))
									Ypos = 0
									
							else:
								print('ERROR 3 !!! Reference glyph not found:\n\t%s=%s' % (glyphname_, code))
								Ypos = 0

					else:
						baseg = Ypos.split('*')[0]
						# print '++++++++', baseg
						shiftY = Ypos.split('*')[1]
						if baseg in font:
							try:
								(xMin, yMin, xMax, Ypos) = font[baseg].bounds
							except:
								print ('ERROR 4 !!! Reference glyph not found:\n\t%s=%s' % ( glyphname_, code ))
								# print '\t', glyphname, code
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
				if replace_anchors and anchorNameExist(glyph, anchorname):
					removeAnchorByName(glyph, anchorname)
				x = getPosByAlign(font, glyph, align, Ypos)
				glyph.appendAnchor(anchorname, (x+shiftX,Ypos))
				# glyph.update()
			

def readAnchorsFromFile(font, filepath = None):
	if not filepath:
		fn = font.fileName + '.anchors_list.txt'
	else:
		fn = filepath
	if os.path.exists(fn):
		print ('='*60)
		print (font.info.familyName, font.info.styleName)
		print ('Loading anchors list from file:')
		print (fn)
		f = open(fn, mode = 'r')
		listofanchors = []
		for line in f:
			line = line.strip()
			listofanchors.append(line)
		f.close()
		return listofanchors

	else:
		print ('ERROR Anchor construction file not found', fn)


def saveAnchors(font):
	print ('=' * 60)
	print (font.info.familyName, font.info.styleName)
	print ('Saving anchors list to file:')
	fn = getAnchorFileName4Save(font)
	print (fn)
	listofanchors = []
	for glyph in font:
		if glyph.anchors:
			anchorlist = '%s=' % glyph.name
			for anchor in glyph.anchors:
				anchorlist += '%s:%i:%i,' % (anchor.name, int(anchor.x), int(anchor.y))

			listofanchors.append( anchorlist[:-1] )
	anchfile = open(fn, mode = 'w')
	anchtxt = '\n'.join(listofanchors)
	anchfile.write(anchtxt)
	anchfile.close()
	print ('File saved.')
	

def placeAnchors(font, anchorsCodeList):
	labels, glyphs, sfxlist, shiftX = parseAnchorsStructure(anchorsCodeList)
	for glyphname, code in resortAnchorsStructure(labels, glyphs).items():
		setAnchor2Glyph(font, glyphname = glyphname, code = code, sfxlist = sfxlist, shiftX = shiftX)

def setAnchorsFromFile(font, saveExistingAnchors = True, anchorsFilePath = None):
	if saveExistingAnchors:
		saveAnchors(font)
	anchorsListConstruction = readAnchorsFromFile(font, anchorsFilePath)
	placeAnchors(font, anchorsListConstruction)

def main():
	if UFOfile:
		font = OpenFont(UFOfile)
	else:
		font = CurrentFont()
	setAnchorsFromFile(font, saveExistingAnchors = saveExistingAnchors, anchorsFilePath = AnchorsRulesFile)
	if saveOutputUFOfile:
		font.save(font.path.replace('.ufo',UFOfile_anchored))


if __name__ == "__main__":
	main()

