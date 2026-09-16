import math
from abc import ABC, abstractmethod

import numpy as np


class SOS(ABC):
    def __init__(self, f_id=-1, fs=48000):
        self.__id = f_id
        self.fs = fs

    @property
    def id(self):
        return self.__id

    @id.setter
    def id(self, id):
        self.__id = id

    @abstractmethod
    def get_sos(self) -> list[list[float]] | None:
        pass


class Biquad(SOS):
    def __init__(self, fs, f_id=-1):
        super().__init__(f_id=f_id, fs=fs)
        self.a, self.b = self._compute_coeffs()
        self.__transfer_function = None

    def __eq__(self, o: object) -> bool:
        equal = self.__class__.__name__ == o.__class__.__name__
        equal &= self.fs == o.fs
        return equal

    def __repr__(self):
        return self.description

    @property
    def description(self):
        description = ""
        if hasattr(self, "display_name"):
            description += self.display_name
        return description

    @property
    def filter_type(self):
        return self.__class__.__name__

    def __len__(self):
        return 1

    @abstractmethod
    def _compute_coeffs(self):
        pass

    @abstractmethod
    def sort_key(self):
        pass

    @staticmethod
    def __format_index(prefix, idx, show_index):
        if show_index:
            return f"{prefix}{idx}="
        else:
            return ""

    def get_sos(self) -> list[list[float]] | None:
        return [np.concatenate((self.b, self.a)).tolist()]


class Gain(Biquad):
    def __init__(self, fs, gain, f_id=-1):
        self.gain = gain
        super().__init__(fs, f_id=f_id)

    @property
    def filter_type(self):
        return "Gain"

    @property
    def display_name(self):
        return "Gain"

    def _compute_coeffs(self):
        return np.array([1.0, 0.0, 0.0]), np.array(
            [10.0 ** (self.gain / 20.0), 0.0, 0.0]
        )

    def resample(self, new_fs):
        """
        Creates a filter at the specified fs.
        :param new_fs: the new fs.
        :return: the new filter.
        """
        return Gain(new_fs, self.gain, f_id=self.id)

    def sort_key(self):
        return f"00000{self.gain:05}{self.filter_type}"

    def to_json(self):
        return {"_type": self.__class__.__name__, "fs": self.fs, "gain": self.gain}


class BiquadWithQ(Biquad):
    def __init__(self, fs, freq, q, f_id=-1):
        self.freq = round(float(freq), 2)
        self.q = float(q)
        self.w0 = 2.0 * math.pi * freq / fs
        self.cos_w0 = math.cos(self.w0)
        self.sin_w0 = math.sin(self.w0)
        self.alpha = self.sin_w0 / (2.0 * self.q)
        super().__init__(fs, f_id=f_id)

    def __eq__(self, o: object) -> bool:
        return super().__eq__(o) and self.freq == o.freq

    @property
    def description(self):
        return super().description + f" {self.freq}/{self.q:.4g}"

    def sort_key(self):
        return f"{self.freq:05}00000{self.filter_type}"


class Passthrough(Gain):
    def __init__(self, fs=1000, f_id=-1):
        super().__init__(fs, 0, f_id=f_id)

    @property
    def display_name(self):
        return "Passthrough"

    @property
    def description(self):
        return "Passthrough"

    def sort_key(self):
        return "ZZZZZZZZZZZZZZ"

    def resample(self, new_fs):
        return Passthrough(fs=new_fs, f_id=self.id)

    def to_json(self):
        return {"_type": self.__class__.__name__, "fs": self.fs}


class BiquadWithQGain(BiquadWithQ):
    def __init__(self, fs, freq, q, gain, f_id=-1):
        self.gain = round(float(gain), 3)
        super().__init__(fs, freq, q, f_id=f_id)

    def __eq__(self, o: object) -> bool:
        return super().__eq__(o) and self.gain == o.gain

    @property
    def description(self):
        return super().description + f"/{self.gain}dB"

    def sort_key(self):
        return f"{self.freq:05}{self.gain:05}{self.filter_type}"


class PeakingEQ(BiquadWithQGain):
    """
    H(s) = (s^2 + s*(A/Q) + 1) / (s^2 + s/(A*Q) + 1)

            b0 =   1 + alpha*A
            b1 =  -2*cos(w0)
            b2 =   1 - alpha*A
            a0 =   1 + alpha/A
            a1 =  -2*cos(w0)
            a2 =   1 - alpha/A
    """

    def __init__(self, fs, freq, q, gain, f_id=-1):
        super().__init__(fs, freq, q, gain, f_id=f_id)

    @property
    def filter_type(self):
        return "PEQ"

    @property
    def display_name(self):
        return "PEQ"

    def _compute_coeffs(self):
        A = 10.0 ** (self.gain / 40.0)
        a = np.array(
            [1.0 + self.alpha / A, -2.0 * self.cos_w0, 1.0 - self.alpha / A],
            dtype=np.float64,
        )
        b = np.array(
            [1.0 + self.alpha * A, -2.0 * self.cos_w0, 1.0 - self.alpha * A],
            dtype=np.float64,
        )
        return a / a[0], b / a[0]

    def resample(self, new_fs):
        """
        Creates a filter at the specified fs.
        :param new_fs: the new fs.
        :return: the new filter.
        """
        return PeakingEQ(new_fs, self.freq, self.q, self.gain, f_id=self.id)

    def to_json(self):
        return {
            "_type": self.__class__.__name__,
            "fs": self.fs,
            "fc": self.freq,
            "q": self.q,
            "gain": self.gain,
        }


def q_to_s(q, gain):
    """
    translates Q to S for a shelf filter.
    :param q: the Q.
    :param gain: the gain.
    :return: the S.
    """
    return 1.0 / (
        (
            ((1.0 / q) ** 2.0 - 2.0)
            / ((10.0 ** (gain / 40.0)) + 1.0 / (10.0 ** (gain / 40.0)))
        )
        + 1.0
    )


def s_to_q(s, gain):
    """
    translates S to Q for a shelf filter.
    :param s: the S.
    :param gain: the gain.
    :return: the Q.
    """
    A = 10.0 ** (gain / 40.0)
    return 1.0 / math.sqrt(((A + 1.0 / A) * (1.0 / s - 1.0)) + 2.0)


class Shelf(BiquadWithQGain):
    def __init__(self, fs, freq, q, gain, count, f_id=-1):
        self.A = 10.0 ** (gain / 40.0)
        super().__init__(fs, freq, q, gain, f_id=f_id)
        self.count = count
        self.__cached_cascade = None

    def q_to_s(self):
        """
        :return: the filter Q as S
        """
        return q_to_s(self.q, self.gain)

    def __len__(self):
        return self.count

    def flatten(self):
        """
        :return: an iterable of length count of this shelf where each shelf has count=1
        """
        if self.count == 1:
            return [self]
        else:
            return [
                self.__class__(self.fs, self.freq, self.q, self.gain, 1)
            ] * self.count

    def format_biquads(
        self,
        minidsp_style,
        separator=",\n",
        show_index=True,
        to_hex=False,
        fixed_point=False,
    ):
        single = super().format_biquads(
            minidsp_style,
            separator=separator,
            show_index=show_index,
            to_hex=to_hex,
            fixed_point=fixed_point,
        )
        if self.count == 1:
            return single
        elif self.count > 1:
            return single * self.count
        else:
            raise ValueError("Shelf must have non zero count")

    def get_sos(self):
        return super().get_sos() * self.count

    def to_json(self):
        return {
            "_type": self.__class__.__name__,
            "fs": self.fs,
            "fc": self.freq,
            "q": self.q,
            "gain": self.gain,
            "count": self.count,
        }

    @property
    def description(self):
        if self.count > 1:
            return super().description + f" x{self.count}"
        else:
            return super().description


class LowShelf(Shelf):
    """
    lowShelf: H(s) = A * (s^2 + (sqrt(A)/Q)*s + A)/(A*s^2 + (sqrt(A)/Q)*s + 1)

            b0 =    A*( (A+1) - (A-1)*cos(w0) + 2*sqrt(A)*alpha )
            b1 =  2*A*( (A-1) - (A+1)*cos(w0)                   )
            b2 =    A*( (A+1) - (A-1)*cos(w0) - 2*sqrt(A)*alpha )
            a0 =        (A+1) + (A-1)*cos(w0) + 2*sqrt(A)*alpha
            a1 =   -2*( (A-1) + (A+1)*cos(w0)                   )
            a2 =        (A+1) + (A-1)*cos(w0) - 2*sqrt(A)*alpha
    """

    def __init__(self, fs, freq, q, gain, count=1, f_id=-1):
        super().__init__(fs, freq, q, gain, count, f_id=f_id)

    @property
    def filter_type(self):
        return "LS"

    @property
    def display_name(self):
        return "Low Shelf"

    def _compute_coeffs(self):
        A = 10.0 ** (self.gain / 40.0)
        a = np.array(
            [
                (A + 1) + ((A - 1) * self.cos_w0) + (2.0 * math.sqrt(A) * self.alpha),
                -2.0 * ((A - 1) + ((A + 1) * self.cos_w0)),
                (A + 1) + ((A - 1) * self.cos_w0) - (2.0 * math.sqrt(A) * self.alpha),
            ],
            dtype=np.float64,
        )
        b = np.array(
            [
                A
                * (
                    (A + 1)
                    - ((A - 1) * self.cos_w0)
                    + (2.0 * math.sqrt(A) * self.alpha)
                ),
                2.0 * A * ((A - 1) - ((A + 1) * self.cos_w0)),
                A
                * ((A + 1) - ((A - 1) * self.cos_w0) - (2 * math.sqrt(A) * self.alpha)),
            ],
            dtype=np.float64,
        )
        return a / a[0], b / a[0]

    def resample(self, new_fs):
        """
        Creates a filter at the specified fs.
        :param new_fs: the new fs.
        :return: the new filter.
        """
        return LowShelf(new_fs, self.freq, self.q, self.gain, self.count, f_id=self.id)


class HighShelf(Shelf):
    """
    highShelf: H(s) = A * (A*s^2 + (sqrt(A)/Q)*s + 1)/(s^2 + (sqrt(A)/Q)*s + A)

                b0 =    A*( (A+1) + (A-1)*cos(w0) + 2*sqrt(A)*alpha )
                b1 = -2*A*( (A-1) + (A+1)*cos(w0)                   )
                b2 =    A*( (A+1) + (A-1)*cos(w0) - 2*sqrt(A)*alpha )
                a0 =        (A+1) - (A-1)*cos(w0) + 2*sqrt(A)*alpha
                a1 =    2*( (A-1) - (A+1)*cos(w0)                   )
                a2 =        (A+1) - (A-1)*cos(w0) - 2*sqrt(A)*alpha

    """

    def __init__(self, fs, freq, q, gain, count=1, f_id=-1):
        super().__init__(fs, freq, q, gain, count, f_id=f_id)

    def __eq__(self, o: object) -> bool:
        return super().__eq__(o) and self.count == o.count

    @property
    def filter_type(self):
        return "HS"

    @property
    def display_name(self):
        return "High Shelf"

    def _compute_coeffs(self):
        A = self.A
        cos_w0 = self.cos_w0
        alpha = self.alpha
        a = np.array(
            [
                (A + 1) - ((A - 1) * cos_w0) + (2.0 * math.sqrt(A) * alpha),
                2.0 * ((A - 1) - ((A + 1) * cos_w0)),
                (A + 1) - ((A - 1) * cos_w0) - (2.0 * math.sqrt(A) * alpha),
            ],
            dtype=np.float64,
        )
        b = np.array(
            [
                A * ((A + 1) + ((A - 1) * cos_w0) + (2.0 * math.sqrt(A) * alpha)),
                -2.0 * A * ((A - 1) + ((A + 1) * cos_w0)),
                A * ((A + 1) + ((A - 1) * cos_w0) - (2.0 * math.sqrt(A) * alpha)),
            ],
            dtype=np.float64,
        )
        return a / a[0], b / a[0]

    def resample(self, new_fs):
        """
        Creates a filter at the specified fs.
        :param new_fs: the new fs.
        :return: the new filter.
        """
        return HighShelf(new_fs, self.freq, self.q, self.gain, self.count, f_id=self.id)
