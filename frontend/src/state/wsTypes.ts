/* Generated from shared/ws_schema.json by `npm run gen:types`. Do not edit by hand. */
/* eslint-disable */

/**
 * Hospital Twin WebSocket messages, schema version 1
 */
export type ServerMessage = SnapshotMessage | EventsMessage | NetworkMessage | ErrorMessage | FederatedMessage;
export type Id = string;
export type PatientId = string | null;
export type State = 'occupied' | 'cleaning' | 'open' | 'blocked';
export type Beds = BedInfo[];
export type Hair = number;
export type Headscarf = boolean;
export type Skin = number;
export type Top = number;
export type ExpectedDischargeH = number | null;
export type Id1 = string;
export type Kind = 'patient' | 'visitor' | 'nurse' | 'doctor' | 'surgeon' | 'emt';
export type Bed = string | null;
export type Floor = number | null;
export type Room = string | null;
export type Spot = string | null;
export type Vehicle = string | null;
export type Arrive = string;
export type Depart = string;
export type Path = string[];
export type Times = string[];
export type Pose = 'lying' | 'seated' | 'standing' | 'walking';
export type Level = 'low' | 'medium' | 'high';
export type ModelVersion = string;
export type Score = number;
export type TopFactors = [unknown, unknown][];
export type Task = string | null;
export type Unit = string | null;
export type Dbp = number;
export type Hr = number;
export type Rr = number;
export type Sbp = number;
export type Spo2 = number;
export type Temp = number;
export type Entities = Entity[];
export type Frozen = boolean;
export type Id2 = string;
export type Name = string;
export type Status = 'open' | 'diverting' | 'offline';
export type Alerts = number;
export type Capacity = number;
export type Census = number;
export type ErWaitMin = number;
export type Waiting = number;
export type Paused = boolean;
export type Ends = string | null;
export type HospitalId = string | null;
export type Id3 = string;
export type Name1 = 'flu_surge' | 'mass_casualty' | 'staff_shortage' | 'hospital_offline';
export type Started = string;
export type Scenarios = ScenarioInfo[];
export type SimTime = string;
export type Speed = number;
export type Type = 'snapshot';
export type V = 1;
export type Id4 = string;
export type Kind1 = 'ambulance' | 'helicopter';
export type Slot = string | null;
export type Status1 = 'at_base' | 'to_scene' | 'on_scene' | 'to_hospital' | 'unloading' | 'returning' | 'transferring';
export type Vehicles = VehicleAtHospital[];
export type Arrive1 = string;
export type Depart1 = string;
export type EntityId = string;
export type Kind2 = 'move';
export type Path1 = string[];
export type Time = string;
export type Times1 = string[];
export type Kind3 = 'spawn';
export type Time1 = string;
export type EntityId1 = string;
export type Kind4 = 'despawn';
export type Reason = 'discharged' | 'transferred' | 'left' | 'off_duty' | 'boarded_vehicle';
export type Time2 = string;
export type Kind5 = 'vitals';
export type PatientId1 = string;
export type Time3 = string;
export type Kind6 = 'risk';
export type Level1 = 'low' | 'medium' | 'high';
export type ModelVersion1 = string;
export type PatientId2 = string;
export type Score1 = number;
export type Time4 = string;
export type TopFactors1 = [unknown, unknown][];
export type Hours = number;
export type Kind7 = 'los';
export type ModelVersion2 = string;
export type PatientId3 = string;
export type Time5 = string;
export type BedId = string;
export type Kind8 = 'bed';
export type PatientId4 = string | null;
export type State1 = 'occupied' | 'cleaning' | 'open' | 'blocked';
export type Time6 = string;
export type Complaint = 'respiratory' | 'cardiac' | 'trauma' | 'gi' | 'neuro' | 'infection' | 'other';
export type EncounterId = number;
export type Esi = number;
export type Kind9 = 'arrival';
export type Mode = 'walk_in' | 'ambulance' | 'air';
export type PatientId5 = string;
export type Time7 = string;
export type Esi1 = number;
export type Kind10 = 'triage';
export type PatientId6 = string;
export type Time8 = string;
export type BedId1 = string;
export type Kind11 = 'er_admit';
export type PatientId7 = string;
export type Time9 = string;
export type WaitMin = number;
export type BedId2 = string;
export type Kind12 = 'admit';
export type PatientId8 = string;
export type Time10 = string;
export type Unit1 = string;
export type Kind13 = 'surgery';
export type PatientId9 = string;
export type Phase = 'start' | 'end';
export type Time11 = string;
export type Expedited = boolean;
export type Kind14 = 'discharge';
export type LosH = number;
export type PatientId10 = string;
export type Time12 = string;
export type Kind15 = 'transfer';
export type PatientId11 = string;
export type Time13 = string;
export type ToHospital = string;
export type VehicleId = string;
export type Kind16 = 'critical';
export type PatientId12 = string;
export type Response = 'icu_transfer' | 'rapid_response';
export type Time14 = string;
export type Unit2 = string;
export type Kind17 = 'alert';
export type Level2 = 'low' | 'medium' | 'high';
export type PatientId13 = string;
export type Score2 = number;
export type Time15 = string;
export type Change = 'on_duty' | 'off_duty';
export type EntityId2 = string;
export type Kind18 = 'staff';
export type Reason1 = string;
export type Time16 = string;
export type Destination = string | null;
export type Kind19 = 'ambulance';
export type PatientId14 = string | null;
export type Slot1 = string | null;
export type Status2 = 'at_base' | 'to_scene' | 'on_scene' | 'to_hospital' | 'unloading' | 'returning' | 'transferring';
export type Time17 = string;
export type VehicleId1 = string;
export type VehicleKind = 'ambulance' | 'helicopter';
export type Kind20 = 'hospital_status';
export type Reason2 = string;
export type Status3 = 'open' | 'diverting' | 'offline';
export type Time18 = string;
export type Until = string | null;
export type HospitalId1 = string | null;
export type Kind21 = 'scenario';
export type Name2 = 'flu_surge' | 'mass_casualty' | 'staff_shortage' | 'hospital_offline';
export type ScenarioId = string;
export type Status4 = 'started' | 'stopped' | 'ended';
export type Time19 = string;
export type Action = 'divert_ambulances' | 'expedite_discharge' | 'move_patient' | 'call_in_staff' | 'hold_bed';
export type Kind22 = 'action';
export type Result = string;
export type Time20 = string;
export type Feature = string;
export type Kind23 = 'drift_alert';
export type Psi = number;
export type Time21 = string;
export type Kind24 = 'agent_rec';
export type Action1 = 'divert_ambulances' | 'expedite_discharge' | 'move_patient' | 'call_in_staff' | 'hold_bed';
export type Name3 = string;
export type Value = number;
export type CitedMetrics = CitedMetric[];
export type Created = string;
export type HospitalId2 = string;
export type Id5 = string;
export type Label = string | null;
export type Rationale = string;
export type Source = 'gemini' | 'rules';
export type Status5 = 'pending' | 'approved' | 'dismissed' | 'expired';
export type Targets = string[];
export type Time22 = string;
export type Events = (
  | MoveEvent
  | SpawnEvent
  | DespawnEvent
  | VitalsEvent
  | RiskEvent
  | LosEvent
  | BedEvent
  | ArrivalEvent
  | TriageEvent
  | ErAdmitEvent
  | AdmitEvent
  | SurgeryEvent
  | DischargeEvent
  | TransferEvent
  | CriticalEvent
  | AlertEvent
  | StaffEvent
  | AmbulanceEvent
  | HospitalStatusEvent
  | ScenarioEvent
  | ActionEvent
  | DriftAlertEvent
  | AgentRecEvent
)[];
export type Frozen1 = boolean;
export type Paused1 = boolean;
export type SimTime1 = string;
export type Speed1 = number;
export type Type1 = 'events';
export type V1 = 1;
export type Frozen2 = boolean;
export type Id6 = string;
export type Lat = number;
export type Lon = number;
export type Name4 = string;
export type Status6 = 'open' | 'diverting' | 'offline';
export type StatusUntil = string | null;
export type Hospitals = NetworkHospital[];
export type Paused2 = boolean;
export type Scenarios1 = ScenarioInfo[];
export type SimTime2 = string;
export type Speed2 = number;
export type Type2 = 'network';
export type V2 = 1;
export type Destination1 = string | null;
export type Home = string;
export type Id7 = string;
export type Kind25 = 'ambulance' | 'helicopter';
export type Lat1 = number;
export type Lon1 = number;
export type PatientId15 = string | null;
export type Lat2 = number;
export type Lon2 = number;
export type T = string;
export type Route = RoutePoint[];
export type Status7 = 'at_base' | 'to_scene' | 'on_scene' | 'to_hospital' | 'unloading' | 'returning' | 'transferring';
export type Vehicles1 = NetworkVehicle[];
export type Message = string;
export type Type3 = 'error';
export type V3 = 1;
export type Error = string | null;
export type Round = number;
export type Rounds = number;
export type Status8 = 'idle' | 'running' | 'done' | 'failed';
export type Type4 = 'federated';
export type V4 = 1;
export type ValAuroc = number[];

export interface SnapshotMessage {
  beds: Beds;
  entities: Entities;
  frozen: Frozen;
  hospital: HospitalRef;
  kpis: Kpis;
  paused: Paused;
  scenarios: Scenarios;
  sim_time: SimTime;
  speed: Speed;
  type?: Type;
  v?: V;
  vehicles: Vehicles;
}
export interface BedInfo {
  id: Id;
  patient_id: PatientId;
  state: State;
}
export interface Entity {
  appearance: Appearance;
  expected_discharge_h?: ExpectedDischargeH;
  id: Id1;
  kind: Kind;
  location: Location;
  move?: Move | null;
  pose: Pose;
  risk?: Risk | null;
  task?: Task;
  unit?: Unit;
  vitals?: Vitals | null;
}
export interface Appearance {
  hair: Hair;
  headscarf: Headscarf;
  skin: Skin;
  top?: Top;
}
/**
 * Where an entity is. In a building: floor and room, plus the bed, seat or spot it holds (seat ids are
 * given in `spot`). In a vehicle: `vehicle` is set and the rest may be empty.
 */
export interface Location {
  bed?: Bed;
  floor: Floor;
  room: Room;
  spot?: Spot;
  vehicle?: Vehicle;
}
/**
 * A walk along the waypoint graph. `times[i]` is when the walker reaches `path[i]`; a pause between two
 * nodes (waiting for the elevator) shows as two equal positions with different times.
 */
export interface Move {
  arrive: Arrive;
  depart: Depart;
  path: Path;
  times: Times;
}
export interface Risk {
  level: Level;
  model_version: ModelVersion;
  score: Score;
  top_factors: TopFactors;
}
export interface Vitals {
  dbp: Dbp;
  hr: Hr;
  rr: Rr;
  sbp: Sbp;
  spo2: Spo2;
  temp: Temp;
}
export interface HospitalRef {
  id: Id2;
  name: Name;
  status: Status;
}
export interface Kpis {
  alerts: Alerts;
  capacity: Capacity;
  census: Census;
  er_wait_min: ErWaitMin;
  waiting: Waiting;
}
export interface ScenarioInfo {
  ends: Ends;
  hospital_id: HospitalId;
  id: Id3;
  name: Name1;
  started: Started;
}
/**
 * A vehicle on this hospital's grounds: an ambulance in a bay slot or the helicopter on the roof.
 */
export interface VehicleAtHospital {
  id: Id4;
  kind: Kind1;
  slot: Slot;
  status: Status1;
}
export interface EventsMessage {
  events: Events;
  frozen: Frozen1;
  kpis: Kpis;
  paused: Paused1;
  sim_time: SimTime1;
  speed: Speed1;
  type?: Type1;
  v?: V1;
}
export interface MoveEvent {
  arrive: Arrive1;
  depart: Depart1;
  entity_id: EntityId;
  from: Location;
  kind?: Kind2;
  path: Path1;
  time: Time;
  times: Times1;
  to: Location;
}
export interface SpawnEvent {
  entity: Entity;
  kind?: Kind3;
  time: Time1;
}
export interface DespawnEvent {
  entity_id: EntityId1;
  kind?: Kind4;
  reason: Reason;
  time: Time2;
}
export interface VitalsEvent {
  kind?: Kind5;
  patient_id: PatientId1;
  time: Time3;
  vitals: Vitals;
}
export interface RiskEvent {
  kind?: Kind6;
  level: Level1;
  model_version: ModelVersion1;
  patient_id: PatientId2;
  score: Score1;
  time: Time4;
  top_factors: TopFactors1;
}
/**
 * The length-of-stay model's latest prediction of the hours until a patient goes home.
 */
export interface LosEvent {
  hours: Hours;
  kind?: Kind7;
  model_version: ModelVersion2;
  patient_id: PatientId3;
  time: Time5;
}
export interface BedEvent {
  bed_id: BedId;
  kind?: Kind8;
  patient_id: PatientId4;
  state: State1;
  time: Time6;
}
export interface ArrivalEvent {
  complaint: Complaint;
  encounter_id: EncounterId;
  esi: Esi;
  kind?: Kind9;
  mode: Mode;
  patient_id: PatientId5;
  time: Time7;
}
export interface TriageEvent {
  esi: Esi1;
  kind?: Kind10;
  patient_id: PatientId6;
  time: Time8;
}
export interface ErAdmitEvent {
  bed_id: BedId1;
  kind?: Kind11;
  patient_id: PatientId7;
  time: Time9;
  wait_min: WaitMin;
}
export interface AdmitEvent {
  bed_id: BedId2;
  kind?: Kind12;
  patient_id: PatientId8;
  time: Time10;
  unit: Unit1;
}
export interface SurgeryEvent {
  kind?: Kind13;
  patient_id: PatientId9;
  phase: Phase;
  time: Time11;
}
export interface DischargeEvent {
  expedited: Expedited;
  kind?: Kind14;
  los_h: LosH;
  patient_id: PatientId10;
  time: Time12;
}
export interface TransferEvent {
  kind?: Kind15;
  patient_id: PatientId11;
  time: Time13;
  to_hospital: ToHospital;
  vehicle_id: VehicleId;
}
/**
 * Escalation to ICU or a rapid response. These are the deterioration model's labels (§5.4).
 */
export interface CriticalEvent {
  kind?: Kind16;
  patient_id: PatientId12;
  response: Response;
  time: Time14;
  unit: Unit2;
}
export interface AlertEvent {
  kind?: Kind17;
  level: Level2;
  patient_id: PatientId13;
  score: Score2;
  time: Time15;
}
export interface StaffEvent {
  change: Change;
  entity_id: EntityId2;
  kind?: Kind18;
  reason: Reason1;
  time: Time16;
}
export interface AmbulanceEvent {
  destination: Destination;
  kind?: Kind19;
  patient_id: PatientId14;
  slot: Slot1;
  status: Status2;
  time: Time17;
  vehicle_id: VehicleId1;
  vehicle_kind: VehicleKind;
}
export interface HospitalStatusEvent {
  kind?: Kind20;
  reason: Reason2;
  status: Status3;
  time: Time18;
  until: Until;
}
export interface ScenarioEvent {
  hospital_id: HospitalId1;
  kind?: Kind21;
  name: Name2;
  params: Params;
  scenario_id: ScenarioId;
  status: Status4;
  time: Time19;
}
export interface Params {
  [k: string]: string | number;
}
export interface ActionEvent {
  action: Action;
  kind?: Kind22;
  params: Params1;
  result: Result;
  time: Time20;
}
export interface Params1 {
  [k: string]: string | number | string[];
}
/**
 * A feature's distribution at a hospital moved away from the training data (PSI above 0.2).
 */
export interface DriftAlertEvent {
  feature: Feature;
  kind?: Kind23;
  psi: Psi;
  time: Time21;
}
/**
 * A new or updated recommendation from the operations agent.
 */
export interface AgentRecEvent {
  kind?: Kind24;
  rec: AgentRecModel;
  time: Time22;
}
export interface AgentRecModel {
  action: Action1;
  cited_metrics: CitedMetrics;
  created: Created;
  hospital_id: HospitalId2;
  id: Id5;
  label?: Label;
  params: Params2;
  rationale: Rationale;
  source: Source;
  status: Status5;
  targets: Targets;
}
export interface CitedMetric {
  name: Name3;
  value: Value;
}
export interface Params2 {
  [k: string]: string | number | string[];
}
export interface NetworkMessage {
  frozen: Frozen2;
  hospitals: Hospitals;
  paused: Paused2;
  scenarios: Scenarios1;
  sim_time: SimTime2;
  speed: Speed2;
  type?: Type2;
  v?: V2;
  vehicles: Vehicles1;
}
export interface NetworkHospital {
  id: Id6;
  kpis: Kpis;
  lat: Lat;
  lon: Lon;
  name: Name4;
  status: Status6;
  status_until: StatusUntil;
}
export interface NetworkVehicle {
  destination: Destination1;
  home: Home;
  id: Id7;
  kind: Kind25;
  lat: Lat1;
  lon: Lon1;
  patient_id: PatientId15;
  route: Route;
  status: Status7;
}
export interface RoutePoint {
  lat: Lat2;
  lon: Lon2;
  t: T;
}
export interface ErrorMessage {
  message: Message;
  type?: Type3;
  v?: V3;
}
/**
 * Progress of a federated training run, sent to everyone connected to the network stream.
 */
export interface FederatedMessage {
  error?: Error;
  round: Round;
  rounds: Rounds;
  status: Status8;
  type?: Type4;
  v?: V4;
  val_auroc: ValAuroc;
}
