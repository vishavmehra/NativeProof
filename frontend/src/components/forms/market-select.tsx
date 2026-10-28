"use client";

import { ChevronsUpDown } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Market } from "@/lib/api/types";

// ISO 3166-1 alpha-2 officially assigned codes. Intl has no region enumeration, so the list lives here.
const CODES =
  "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW";

const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

export const MARKETS: Market[] = CODES.split(" ")
  .map((code) => ({ country_code: code, display_name: regionNames.of(code) ?? code }))
  .sort((a, b) => a.display_name.localeCompare(b.display_name));

/** Searchable single-market picker (name or ISO code). Labels associate through `id`. */
export function MarketSelect({ value, onChange, id }: { value: Market | null; onChange(m: Market): void; id?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        id={id}
        render={<Button variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between bg-surface font-normal" />}
      >
        {value ? (
          <span className="truncate">
            {value.display_name} <span className="font-mono text-xs text-ink-secondary">{value.country_code}</span>
          </span>
        ) : (
          <span className="text-ink-secondary">Select a market</span>
        )}
        <ChevronsUpDown aria-hidden className="opacity-50" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-(--anchor-width) min-w-64 p-0">
        <Command>
          <CommandInput placeholder="Search country or ISO code" aria-label="Search markets" />
          <CommandList>
            <CommandEmpty>No country matches.</CommandEmpty>
            <CommandGroup>
              {MARKETS.map((m) => (
                <CommandItem
                  key={m.country_code}
                  value={`${m.display_name} ${m.country_code}`}
                  data-checked={value?.country_code === m.country_code}
                  onSelect={() => {
                    onChange(m);
                    setOpen(false);
                  }}
                >
                  <span className="truncate">{m.display_name}</span>
                  <span className="font-mono text-[11px] text-ink-secondary">{m.country_code}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
