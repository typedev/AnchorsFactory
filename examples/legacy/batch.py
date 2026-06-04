import os
import glob
from tdAnchorsFactory import TDAnchorsFactory

def getFilesList (fontsFolder, ext = '*.ufo'):
    path = os.path.join(fontsFolder, ext)
    return glob.glob(path)

if __name__ == "__main__":
    folder = '...'
    files = getFilesList(folder)
    print(files)
    for file in files:
        print(file)
        factory = TDAnchorsFactory(
            UFOfile=file,
            AnchorsRulesFile='default-anchors-list.txt',
            clear_exist_anchors=True,
            replace_anchors=True,
            saveOutputUFOfile=False,
            saveExistingAnchors=False,
            log_directory='logs'
        )
        factory.run()