"""Official employer routing for the live Management Trainee catalogue."""

from hk_jobs.mt_employer_links import employer_destination_for


def test_hkma_manager_trainee_uses_the_official_vacancies_page():
    route = employer_destination_for("Hong Kong Monetary Authority (HKMA)", "Manager Trainee (2027 Intake)")

    assert route is not None
    assert route.url == "https://www.hkma.gov.hk/eng/about-us/join-us/current-vacancies/"
    assert route.kind == "employer_vacancies"


def test_bochk_mt_routes_to_employer_programme_or_vacancies_page():
    programme = employer_destination_for("Bank Of China (Hong Kong) Limited", "2027 Management Trainee Programme")
    wealth = employer_destination_for("Bank Of China (Hong Kong) Limited", "Wealth Management Trainee Programme")

    assert programme is not None
    assert programme.kind == "employer_role"
    assert programme.url == "https://www.bochk.com/en/career/ustudentprogramme/mgttrainee.html"
    assert wealth is not None
    assert wealth.kind == "employer_vacancies"


def test_no_official_destination_is_invented_for_an_unlisted_mt_role():
    assert employer_destination_for("Hang Seng Bank", "Management Trainee Programme") is None
