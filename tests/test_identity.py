from checker.core.ingest import find_srns, student_id_from_filename


def test_srn_from_messy_filenames():
    assert student_id_from_filename("PES1UG25CS138 - Name.pdf") == "PES1UG25CS138"
    assert student_id_from_filename("CN_LAB1_pes1ug25cs700.pdf") == "PES1UG25CS700"
    assert student_id_from_filename("PES1202604133_CN_lab.pdf") == "PES1202604133"
    assert student_id_from_filename("B.VISHNU VARDHAN.pdf") == "B.VISHNU VARDHAN"


def test_find_srns_in_cover_text():
    assert find_srns("NAME: X  SRN : PES1UG25CS691 DATE") == ["PES1UG25CS691"]
