"""Build an honest, readable response from already saved results after a failure."""


def recovery_report(profile, findings, notes=()):
    has_findings = bool(findings)
    columns = [column['name'] for column in profile.get('columns', [])][:12]
    summary = (
        'I could complete part of your analysis. The verified findings are below; some parts of your question remain unanswered.'
        if has_findings else
        'I could not complete the calculations for this question, so I cannot give you a reliable numerical answer yet.'
    )
    data_notes = []
    if profile.get('row_count') is not None:
        data_notes.append(f"The saved dataset profile contains {profile['row_count']} records and {profile.get('column_count', len(columns))} columns.")
    if not has_findings and columns:
        data_notes.append('Available fields include: ' + ', '.join(columns) + '.')
    return {
        'executive_summary': summary,
        'key_findings': findings,
        'statistical_findings': [],
        'data_notes': data_notes,
        'limitations': list(dict.fromkeys([
            'Some steps could not be completed. Missing results have not been estimated.',
            'No conclusions about statistical significance or causes are included in this recovery response.',
            *notes,
        ])),
        'recommendations': [] if has_findings else ['Try one specific metric and comparison at a time, or retry this question shortly.'],
    }
