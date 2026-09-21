"""Choose first-window offsets after transmitter startup responses."""


HISTORICAL_FIRST_OFFSET_MIN = 50
HISTORICAL_FIRST_OFFSET_MAX = 500
FIRST_OFFSET_SPAN = (HISTORICAL_FIRST_OFFSET_MAX -
                     HISTORICAL_FIRST_OFFSET_MIN)

# The delay analysis measures a maximum operational response-end displacement
# of five samples for the configured dynamic channel. This is an empirical
# bound for the pinned channel policy, not a general GNU Radio channel bound.
CHANNEL_OPERATIONAL_DELAY_SAMPLES = 5

LINEAR_MODULATIONS = frozenset(
    ('BPSK', 'QPSK', '8PSK', 'PAM4', 'QAM16', 'QAM64'))


def transmitter_startup_samples(modulation, samples_per_symbol,
                                fixed_am_ssb=False, fixed_wbfm=False):
    """Return the first sample after the transmitter startup response.

    FIR paths use their structural response boundary. WBFM contains an IIR
    preemphasis stage, so its values use the reproducible ``1e-7`` tail-energy
    measurement from ``scripts/analyze_filter_delay.py``.

    Args:
        modulation: RadioML modulation name.
        samples_per_symbol: Actual SPS, or zero for an analog modulation.
        fixed_am_ssb: Whether the repaired AM-SSB oscillator is selected.
        fixed_wbfm: Whether the WBFM rate repair is selected.

    Returns:
        Zero-based index of the first sample beyond the startup response.

    Raises:
        ValueError: If the modulation or SPS value is invalid.
    """
    if modulation in LINEAR_MODULATIONS:
        if samples_per_symbol < 1:
            raise ValueError('linear modulation requires positive SPS')
        # The PFB uses 32*11*SPS RRC taps. Its integer-SPS output response is
        # no longer than 11*SPS**2+1 samples, including GNU Radio's end tap.
        return 11 * samples_per_symbol**2 + 1
    if modulation == 'GFSK':
        if samples_per_symbol < 2:
            raise ValueError('GFSK requires SPS of at least two')
        # GNU Radio convolves 4*SPS Gaussian taps with an SPS-wide rectangle.
        return 5 * samples_per_symbol
    if modulation == 'CPFSK':
        if samples_per_symbol < 1:
            raise ValueError('CPFSK requires positive SPS')
        return samples_per_symbol + 1
    if samples_per_symbol != 0:
        raise ValueError('analog modulation requires zero SPS')
    if modulation == 'WBFM':
        return 255 if fixed_wbfm else 313
    if modulation == 'AM-DSB':
        return 5
    if modulation == 'AM-SSB':
        # The historical zero-frequency sine suppresses the message before
        # the Hilbert FIR. The repaired path has measured support through 403.
        return 404 if fixed_am_ssb else 0
    raise ValueError('unknown modulation: %s' % modulation)


def settled_window_guard(modulation, samples_per_symbol,
                         fixed_am_ssb=False, fixed_wbfm=False):
    """Return the conservative first-window lower bound for one transmission.

    The historical lower bound of 50 remains in force for short-memory paths.
    Longer paths add the measured channel response-end displacement to the
    first sample beyond the transmitter response.
    """
    transmitter_guard = transmitter_startup_samples(
        modulation, samples_per_symbol, fixed_am_ssb, fixed_wbfm)
    return max(HISTORICAL_FIRST_OFFSET_MIN,
               transmitter_guard + CHANNEL_OPERATIONAL_DELAY_SAMPLES)


def first_window_offset_bounds(modulation, samples_per_symbol,
                               settled_windows=False, fixed_am_ssb=False,
                               fixed_wbfm=False):
    """Return inclusive bounds for the first-window offset RNG draw."""
    if settled_windows:
        minimum = settled_window_guard(
            modulation, samples_per_symbol, fixed_am_ssb, fixed_wbfm)
    else:
        minimum = HISTORICAL_FIRST_OFFSET_MIN
    return minimum, minimum + FIRST_OFFSET_SPAN
