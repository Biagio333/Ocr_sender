# ollama run hf.co/mradermacher/poker-reasoning-14b-GGUF:Q3_K_S
#nc -u -l 9000
#nc -u -l 9001 | jq -C

import cv2
import os
from pathlib import Path

from matplotlib.table import Table
from scraper.Scren_cap_cel import  OCRReader
from scraper.roi_map import ROIMap
from scraper.table_reader import TableReader
from scraper.Image_search import image_search
from Impostazioni import *
from utils.ADB import adb_tap
from utils.utils import load_scraper_frame, save_adb_screenshot
from utils.debug_mjpeg import MJPEGDebugServer

import time



def main():
    count = -1
    saved_screenshot_count = DEBUG_START_FRAME_NUMBER
    old_table_street = None
    table_hero_cards_old = []

    # creazione cartella per salvataggio screenshot se necessario
    if SCRENSHOT_TYPE == SCR_TYPE.ADB and SAVE_SCREENSHOT:
        os.makedirs(Path(SAVE_SCREENSHOT_DIR), exist_ok=True)

    #per debug: mostra il video con i risultati OCR disegnati sopra
    server = MJPEGDebugServer(host="127.0.0.1", port=5000, jpeg_quality=80)
    server.start()

    roi_map = ROIMap(DATA_DIR / f"{table_name}.json")
    roi_map.load(DISPLAY_SCALE)  

    # Inizializza image_search e carica le immagini
    img_search = image_search(roi_map, table_name, scale_factor=DISPLAY_SCALE)
    img_search.load_images(table_name)  #

    if SCRENSHOT_TYPE == SCR_TYPE.ADB :
        ocr = OCRReader(scale=DISPLAY_SCALE, gray=False, min_score=0.5)
        ocr.start_capture()

    if SCRENSHOT_TYPE == SCR_TYPE.IMMAGE_SAVED:
        ocr = OCRReader(scale=DISPLAY_SCALE, gray=False, min_score=0.5)

    


    # loop principale ----------------------------------------------------------------------
    while True:

        t0 = time.time()

        # Carica il frame (da ADB o da cartella)
        frame_data = load_scraper_frame(
            screenshot_type=SCRENSHOT_TYPE,
            ocr=ocr,
            display_scale=DISPLAY_SCALE,
            save_screenshot_dir=SAVE_SCREENSHOT_DIR,
            debug_start_frame_number=DEBUG_START_FRAME_NUMBER,
            saved_screenshot_count=saved_screenshot_count,
            count=count,
        )

        count = frame_data["count"]
        saved_screenshot_count = frame_data["saved_screenshot_count"]
        img = frame_data["img"]
        img_full = frame_data["img_full"]

        if frame_data["skipped"]:
            continue


        img_for_ocr = img_search.apply_ocr_mask(img)

        t0 = time.time()
        ocr_results, ocr_time = ocr.run_ocr(img_for_ocr)
        elapsed_ocr = time.time() - t0


        img_populated = ocr.draw_results(img_for_ocr, ocr_results, 0)  # disegna i risultati OCR sulla stessa immagine usata dall'OCR
        server.update_frame(img_populated)

        # salva screenshot se modalità ADB e opzione attiva     
        if SCRENSHOT_TYPE == SCR_TYPE.ADB and SAVE_SCREENSHOT:
            saved_screenshot_count = save_adb_screenshot(
                img_full=img_full,
                save_screenshot_dir=SAVE_SCREENSHOT_DIR,
                saved_screenshot_count=saved_screenshot_count,
            )

        # aspetto fronte salita carte in mano
        #if old_table_street is not None and old_table_street == "preflop":
        #    table_reader = TableReader(roi_map, ocr_results, img_search)
        






        








if __name__ == "__main__":
    main()
