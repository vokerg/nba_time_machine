import test from "node:test";
import assert from "node:assert/strict";
import { parseDisclosure } from "../src/guide.ts";
const id = "00000000-0000-0000-0000-000000000001";
const cursor = "2026-10-14T12:00:00Z";
const slate = {
  time_cursor: cursor,
  games: [{ game_id: id, state: "sealed", disclosure: "pregame" }],
};
const base = { time_cursor: cursor, as_of: cursor, details: {}, game_ids: [] };
const rating = {
  game_id: id,
  rating: 8,
  model: "postgame-v1",
  as_of: cursor,
  components: [
    {
      label: "Close late play",
      points: 8,
      normalized: 0.8,
      source_ref: "fixture:1",
      observed_at: cursor,
      available_at: cursor,
    },
  ],
};
test("guide rejects off-slate, duplicate, cross-layer, inconsistent and future evidence", () => {
  const bad = [
    [{ ...base, game_ids: [id, id] }, "order"],
    [{ ...base, game_ids: ["00000000-0000-0000-0000-000000000099"] }, "order"],
    [{ ...base, details: { [id]: rating } }, "verdict"],
    [{ ...base, details: { [id]: rating } }, "clue"],
    [
      {
        ...base,
        details: {
          [id]: { game_id: id, result: { home_score: 100, away_score: 90 } },
        },
      },
      "rating",
    ],
    [{ ...base, details: { [id]: { ...rating, rating: 9 } } }, "rating"],
    [
      {
        ...base,
        details: { [id]: { ...rating, as_of: "2026-10-15T00:00:00Z" } },
      },
      "rating",
    ],
    [
      { ...base, details: { [id]: { ...rating, raw_payload: "unsafe" } } },
      "rating",
    ],
    [{ ...base, time_cursor: "2026-10-15T00:00:00Z" }, "order"],
  ];
  for (const [value, level] of bad)
    assert.throws(() => parseDisclosure(value, slate, level));
  assert.equal(
    parseDisclosure({ ...base, details: { [id]: rating } }, slate, "rating", id)
      .details[id].rating,
    8,
  );
});

const expectation = {
  model: 'pregame-records-v1', rating: 4, overall_points: .8, coverage: 'records-only', basis: 'reconstructed',
  explanation: 'Entering records with conservative sample confidence.', missing: ['Injuries'],
  teams: [{team:'BOS',wins:20,losses:5,smoothed_win_pct:.714}, {team:'NYK',wins:18,losses:7,smoothed_win_pct:.657}],
  sample_confidence: 1, formula: 'Shared record-strength formula', source_ref: 'fact:1', observed_at: cursor, available_at: cursor,
};
test('open expectation is allowlisted, slate-scoped, reconstructed and isolated from Time Machine', async () => {
  const { parseGuideList } = await import('../src/guide.ts');
  const value = {...slate, expectations:{[id]:expectation}};
  assert.equal(parseGuideList(value, 'browse').expectations[id].rating, 4);
  assert.throws(() => parseGuideList(value, 'time-machine'));
  for (const extra of [{home_score:110}, {removed_result:'win'}, {rating:11}, {overall_points:2},
      {teams:[{...expectation.teams[0],provider_after_wins:21}, expectation.teams[1]]}]) {
    assert.throws(() => parseGuideList({...slate, expectations:{[id]:{...expectation,...extra}}}, 'browse'));
  }
  assert.throws(() => parseGuideList({...slate, expectations:{'unknown-game':expectation}}, 'browse'));
});

test('known pre-tip star potential survives missing records and rejects minutes, later rosters and cross-cutoff inputs', async () => {
  const {parseGuideList} = await import('../src/guide.ts');
  const tip='2026-10-14T00:00:00Z', known='2026-10-13T10:00:00Z';
  const value={...slate,games:[{...slate.games[0],scheduled_tip:tip}],expectations:{[id]:{
    model:'pregame-context-v2',rating:6.4516,overall_points:.9677,coverage:'stars-only',basis:'known-pre-tip',
    explanation:'Roster potential; availability unconfirmed.',missing:['Regular-season record strength'],
    teams:[{team:'BOS'},{team:'NYK'}],formula:'Shared rank/slot/team formula',source_ref:'ranking:fixture',observed_at:known,available_at:known,
    star_power:{rating:6.4516,overall_points:.9677,explanation:'Unconfirmed availability',
      teams:['BOS','NYK'].map((team,i)=>({team,normalized:1/1.55,players:[{name:'Fixture '+i,rank:i+1,slot_weight:1,contribution:1}],
        ranked_players:[{name:'Fixture '+i,rank:i+1,slot_weight:1,contribution:1},{name:'Fourth '+i,rank:i+10,slot_weight:0,contribution:0}]})),
      evidence:[0,1,2].map(i=>({source_ref:'fixture:'+i,observed_at:known,available_at:known}))}
  }}};
  assert.equal(parseGuideList(value,'browse').expectations[id].coverage,'stars-only');
  assert.equal(parseGuideList(value,'time-machine').expectations[id].rating,6.4516);
  const badMinutes=structuredClone(value);badMinutes.expectations[id].star_power.teams[0].players[0].minutes=48;
  assert.throws(()=>parseGuideList(badMinutes,'browse'));
  const badTip=structuredClone(value);badTip.expectations[id].star_power.evidence[0].observed_at=tip;
  assert.throws(()=>parseGuideList(badTip,'browse'));
  const badCutoff=structuredClone(value);badCutoff.time_cursor='2026-10-13T09:00:00Z';
  assert.throws(()=>parseGuideList(badCutoff,'time-machine'));
  const duplicateRank=structuredClone(value);duplicateRank.expectations[id].star_power.teams[0].ranked_players[1].rank=1;
  assert.throws(()=>parseGuideList(duplicateRank,'browse'));
  const tooMany=structuredClone(value);tooMany.expectations[id].star_power.teams[0].ranked_players=Array.from({length:41},(_,i)=>({name:'Player '+i,rank:i+1,slot_weight:0,contribution:0}));
  assert.throws(()=>parseGuideList(tooMany,'browse'));
});

test('entering records are independent of rating coverage and cannot carry results or enter Time Machine', async()=>{
  const {parseGuideList}=await import('../src/guide.ts');
  const value={...slate,expectations:{},entering_records:{[id]:{basis:'reconstructed',
    teams:[{team:'BOS',wins:1,losses:0},{team:'NYK',wins:0,losses:1}],observed_at:cursor,available_at:cursor}}};
  assert.equal(parseGuideList(value,'browse').entering_records[id].teams[0].wins,1);
  assert.throws(()=>parseGuideList(value,'time-machine'));
  const bad=structuredClone(value);bad.entering_records[id].teams[0].home_score=100;
  assert.throws(()=>parseGuideList(bad,'browse'));
});

test('genuine pre-tip records and expectations pass Time Machine only before both boundaries', async()=>{
  const {parseGuideList}=await import('../src/guide.ts');
  const known='2026-10-13T10:00:00Z', tip='2026-10-14T00:00:00Z';
  const value={...slate,games:[{...slate.games[0],scheduled_tip:tip}],
    expectations:{[id]:{...expectation,basis:'known-pre-tip',observed_at:known,available_at:known}},
    entering_records:{[id]:{basis:'known-pre-tip',teams:[{team:'BOS',wins:20,losses:5},{team:'NYK',wins:18,losses:7}],
      observed_at:known,available_at:known}}};
  assert.equal(parseGuideList(value,'time-machine').entering_records[id].teams[0].wins,20);
  assert.equal(parseGuideList(value,'time-machine').expectations[id].basis,'known-pre-tip');
  for(const field of ['observed_at','available_at']) {
    for(const section of ['expectations','entering_records']) {
      const atTip=structuredClone(value);atTip[section][id][field]=tip;
      assert.throws(()=>parseGuideList(atTip,'browse'));
      const afterCutoff=structuredClone(value);afterCutoff.time_cursor='2026-10-13T09:00:00Z';
      assert.throws(()=>parseGuideList(afterCutoff,'time-machine'));
    }
  }
});
