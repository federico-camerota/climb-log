// SPDX-License-Identifier: GPL-3.0-or-later
// dayjs as the date inputs need it: typed dates parsed with their format (dd/mm/yyyy, 06-ui).
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";

dayjs.extend(customParseFormat);
