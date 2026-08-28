SEED = 42
HORIZON_DAYS = 60
RECENCY_WINDOWS_DAYS = [90, 180]
WRITTEN_OFF_CONSERVATIVE_DAYS = 150

# Experiment A (time-based): fraction of the historical issue_date window
# treated as train (fit+validation+calibration) vs. test.
TIME_SPLIT_TRAIN_MONTHS = 9
TIME_SPLIT_TEST_MONTHS = 2

# Experiment B (customer-based): customer-level train/test split.
CUSTOMER_SPLIT_TRAIN_FRACTION = 0.8
CUSTOMER_SPLIT_VAL_FRACTION_OF_TRAIN = 0.15

# Experiment A: stratified-by-label fraction of the fit pool held out as the
# calibration slice (removed from what actually gets passed to .fit()).
CALIBRATION_FRACTION_OF_FIT = 0.15

# Floor/ceiling applied to calibrated probabilities before evaluation or
# downstream use (the economics engine's EV(a) = P(recovery)*Amount - Cost -
# Friction must never see a literal 0.0/1.0 -- see DECISIONS.md). Deliberate
# operational bound, not a machine epsilon.
CALIBRATED_PROBABILITY_FLOOR = 0.01
CALIBRATED_PROBABILITY_CEILING = 0.99

CLASS_BALANCE_LOW = 0.15
CLASS_BALANCE_HIGH = 0.85

# Day marks for the resolution-delay diagnostic curve.
CUMULATIVE_DAY_MARKS = [30, 60, 90, 120, 150]
