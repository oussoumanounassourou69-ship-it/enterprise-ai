from app.document import _salary_matrix_from_ocr


def make_detection(x, y, text, confidence=0.99):
    box=[[x-8,y-8],[x+8,y-8],[x+8,y+8],[x-8,y+8]]
    return box,text,confidence


def salary_scale_detections(incomplete_echelon=None):
    detections=[make_detection(100,100,'Categories')]
    columns=[250,400,550,700,850,1000,1150]
    detections.extend(make_detection(x,100,label) for x,label in zip(columns,'ABCDEFG'))

    for row_index,echelon in enumerate(range(4,13)):
        row_y=160+row_index*80
        ocr_echelon=6 if echelon==9 else echelon
        detections.append(make_detection(100,row_y,str(ocr_echelon)))
        base=89683+row_index*28000
        step=5605+row_index*300
        for column,x in enumerate(columns):
            if echelon==incomplete_echelon and column>=5:
                continue
            value=base+column*step
            if echelon==4 and column==0:
                value=8968
            detections.append(make_detection(x,row_y,str(value)))
        if echelon!=incomplete_echelon:
            for column,x in enumerate(columns[1:],start=1):
                detections.append(make_detection(x,row_y+38,str(column*step)))
    return detections


def test_salary_matrix_corrects_ocr_errors_from_increment_rows():
    result=_salary_matrix_from_ocr(salary_scale_detections())

    assert result is not None
    assert '| 4 | 89683 | 95288 | 100893 | 106498 | 112103 | 117708 | 123313 |' in result
    assert '| 9 | 229683 | 236788 | 243893 | 250998 | 258103 | 265208 | 272313 |' in result


def test_salary_matrix_rejects_rows_without_enough_ocr_evidence():
    result=_salary_matrix_from_ocr(salary_scale_detections(incomplete_echelon=7))

    assert result is None