from app.services.dataset_loader_service import DatasetLoaderService


def test_csv_preview_is_bounded_and_preserves_column_names():
    rows = ["region,revenue"] + [f"North,{index}" for index in range(8)]
    loaded = DatasetLoaderService(max_rows=100).preview("\n".join(rows).encode(), "csv", 5)

    assert loaded.original_column_names == ["region", "revenue"]
    assert len(loaded.dataframe.index) == 6
    assert loaded.dataframe.iloc[0].to_dict() == {"region": "North", "revenue": 0}

    next_page = DatasetLoaderService(max_rows=100).preview(
        "\n".join(rows).encode(), "csv", 3, 3
    )
    assert next_page.dataframe.iloc[0].to_dict() == {"region": "North", "revenue": 3}


def test_json_preview_is_bounded():
    payload = b'[{"name":"A","value":1},{"name":"B","value":2},{"name":"C","value":3}]'
    loaded = DatasetLoaderService(max_rows=100).preview(payload, "json", 2)

    assert loaded.original_column_names == ["name", "value"]
    assert len(loaded.dataframe.index) == 3

    next_page = DatasetLoaderService(max_rows=100).preview(payload, "json", 1, 1)
    assert next_page.dataframe.iloc[0].to_dict() == {"name": "B", "value": 2}
