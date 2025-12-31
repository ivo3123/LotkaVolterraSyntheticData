import polars as pl
from polars import col as c
from chronos import Chronos2Pipeline
import plotly.graph_objects as go
from typing import Literal
from toolz import partial


def impute_target(
    pl_data: pl.DataFrame,
    target: Literal["Hare", "Lynx"],
    year_to_impute_start: int = 1936,
    year_to_impute_end: int = 2025,
) -> pl.DataFrame:
    pl_context = pl_data.with_columns(
        pl.datetime(pl.col("Year"), 12, 31).alias("YearDT")
    ).select("YearDT", target, pl.lit("lotka-volterra").alias("id"))

    l_future_years = list(range(year_to_impute_start, year_to_impute_end + 1))
    pl_future = pl.DataFrame({"Year": l_future_years}).select(
        pl.datetime(pl.col("Year"), 12, 31).alias("YearDT"),
        pl.lit("lotka-volterra").alias("id"),
    )

    pipeline = Chronos2Pipeline.from_pretrained(
        "amazon/chronos-2",
        device_map="cpu",
    )

    df_pred = pipeline.predict_df(
        pl_context.to_pandas(),
        future_df=pl_future.to_pandas(),
        prediction_length=len(l_future_years),  # Number of steps to forecast
        quantile_levels=[
            0.1,
            0.2,
            0.3,
            0.4,
            0.5,
            0.6,
            0.7,
            0.8,
            0.9,
        ],  # Quantile for probabilistic forecast
        id_column="id",  # Column identifying different time series
        timestamp_column="YearDT",  # Column with datetime information
        target=target,  # Column(s) with time series values to predict
    )

    return pl.from_pandas(df_pred).with_columns(c("YearDT").dt.year().alias("Year"))


impute_hare = partial(impute_target, target="Hare")
impute_lynx = partial(impute_target, target="Lynx")


def add_chosen_quantiles(
    pl_cronos_results: pl.DataFrame, target: Literal["Hare", "Lynx"]
) -> pl.DataFrame:
    def process_row(row):
        val = str(row["chosen_quantile"])
        row[target] = row[str(val)] if val != "nan" else None
        return row

    df_temp = (
        pl_cronos_results.drop("id", "target_name", "predictions")
        .to_pandas()
        .apply(process_row, axis=1)
    )

    return (
        pl.from_pandas(df_temp)
        .with_columns(
            "Year",
            pl.col(target).cast(pl.Int64),
        )
        .drop("", strict=False)
    )


def plot_target(
    pl_dataset: pl.DataFrame,
    target: Literal["Hare", "Lynx"],
    pl_data_original: pl.DataFrame,
):
    pl_temp = add_chosen_quantiles(
        pl_cronos_results=pl_dataset,
        target=target,
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=pl_data_original["Year"],
            y=pl_data_original[target],
            name="Real data",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=pl_temp["Year"],
            y=pl_temp[target],
            line=dict(dash="dash"),
            name="Imputed data",
        )
    )

    fig.update_layout(
        title={"text": str(target), "x": 0.5},
        xaxis_title="Year",
        yaxis_title="Population",
    )

    fig.show()


def get_clean_imputed_data(pl_dataset: pl.DataFrame, target: Literal["Hare", "Lynx"]):
    return add_chosen_quantiles(
        pl_cronos_results=pl_dataset,
        target=target,
    ).select("Year", target)


def main():
    pl_data_original = pl.read_csv("data/lotka_volterra_data.csv")

    pl_hare_imputed = impute_hare(pl_data_original)
    pl_lynx_imputed = impute_lynx(pl_data_original)

    pl_quantiles_hare = pl.read_csv("data/chosen_quantiles_hare.csv")
    pl_quantiles_lynx = pl.read_csv("data/chosen_quantiles_lynx.csv")

    pl_hare_after_chronos = pl_hare_imputed.join(pl_quantiles_hare, on="Year")
    pl_lynx_after_chronos = pl_lynx_imputed.join(pl_quantiles_lynx, on="Year")

    for target, pl_dataset in [
        ("Hare", pl_hare_after_chronos),
        ("Lynx", pl_lynx_after_chronos),
    ]:
        plot_target(pl_dataset, target, pl_data_original)

    pl_data_full = pl.concat(
        [
            pl_data_original,
            get_clean_imputed_data(pl_hare_after_chronos, "Hare").join(
                other=get_clean_imputed_data(pl_lynx_after_chronos, "Lynx"), on="Year"
            ),
        ],
        how="vertical_relaxed",
    )

    pl_data_full.write_csv("output.csv")


if __name__ == "__main__":
    main()
