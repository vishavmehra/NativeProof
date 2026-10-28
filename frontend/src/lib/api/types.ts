/** Readable aliases over the generated contract types. Regenerate schema.d.ts with `npm run gen:api`. */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Market = Schemas["Market"];
export type DataMode = Schemas["Project"]["mode"];
export type Dimension = Schemas["DimensionRating"]["dimension"];
export type ErrorResponse = Schemas["ErrorResponse"];
export type Readiness = Schemas["Readiness"];

export type Project = Schemas["Project"];
export type ProjectSummary = Schemas["ProjectSummary"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectUpdate = Schemas["ProjectUpdate"];
export type Brand = Schemas["Brand"];

export type Campaign = Schemas["Campaign"];
export type CampaignCreate = Schemas["CampaignCreate"];
export type CampaignUpdate = Schemas["CampaignUpdate"];
export type CampaignContent = Schemas["CampaignContent-Output"];
export type CampaignContentInput = Schemas["CampaignContent-Input"];
export type ContentVersion = Schemas["ContentVersion"];
export type EvaluationCriteria = Schemas["EvaluationCriteria"];

export type Run = Schemas["Run"];
export type RunStatus = Schemas["Run"]["status"];
export type RunType = Schemas["Run"]["run_type"];
export type RunAccepted = Schemas["RunAccepted"];
export type RunMetadata = Schemas["RunMetadata"];
export type StepTrace = Schemas["StepTrace"];

export type EvidenceRecord = Schemas["EvidenceRecord"];
export type EvidenceType = Schemas["EvidenceRecord"]["evidence_type"];
export type ClaimType = Schemas["EvidenceRecord"]["claim_type"];
export type RetrievalMode = Schemas["EvidenceRecord"]["retrieval_mode"];
export type ConfidenceLabel = Schemas["BriefFinding"]["confidence_label"];
export type RiskFlag = Schemas["RiskFlag"];

export type DiscoveryCreate = Schemas["DiscoveryCreate"];
export type DiscoveryResult = Schemas["DiscoveryResult"];
export type CulturalReference = Schemas["CulturalReference"];
export type MarketBrief = Schemas["MarketBrief"];
export type BriefFinding = Schemas["BriefFinding"];

export type Study = Schemas["Study"];
export type StudyCreate = Schemas["StudyCreate"];
export type SimulationConfig = Schemas["SimulationConfig-Output"];
export type RehearsalCreate = Schemas["RehearsalCreate"];
export type RehearsalResult = Schemas["RehearsalResult"];
export type SyntheticReaction = Schemas["SyntheticReaction"];
export type DimensionResult = Schemas["DimensionResult"];
export type Finding = Schemas["Finding"];
export type Disagreement = Schemas["Disagreement"];

export type Adaptation = Schemas["Adaptation"];
export type AdaptationCreate = Schemas["AdaptationCreate"];
export type AdaptationRevisionCreate = Schemas["AdaptationRevisionCreate"];
export type ContentChange = Schemas["ContentChange"];

export type EvaluationCreate = Schemas["EvaluationCreate"];
export type EvaluationResult = Schemas["EvaluationResult"];
export type CandidateResult = Schemas["CandidateResult"];
export type Recommendation = Schemas["Recommendation"];
export type ScoringDefinition = Schemas["ScoringDefinition"];

export type Report = Schemas["Report"];
export type ReportSummary = Schemas["ReportSummary"];
export type ReportCreate = Schemas["ReportCreate"];

// v2 (contracts/README §13)
export type ReadinessCapabilities = Schemas["ReadinessCapabilities"];
export type BrandUpdate = Schemas["BrandUpdate"];
export type BrandExample = Schemas["BrandExample-Output"];
export type BrandExampleInput = Schemas["BrandExample-Input"];

export type CulturalProfile = Schemas["CulturalProfile"];
export type CulturalProfileSummary = Schemas["CulturalProfileSummary"];
export type CulturalProfileCreate = Schemas["CulturalProfileCreate"];
export type CulturalProfileUpdate = Schemas["CulturalProfileUpdate"];
export type ProfileItem = Schemas["ProfileItem"];

export type MarketComparison = Schemas["MarketComparison"];
export type MarketComparisonSummary = Schemas["MarketComparisonSummary"];
export type MarketComparisonCreate = Schemas["MarketComparisonCreate"];
export type MarketColumn = Schemas["MarketColumn"];
export type MarketComparability = Schemas["MarketComparability"];
export type EvidenceQuality = Schemas["EvidenceQuality"];
export type BrandCompatibility = Schemas["BrandCompatibility"];

export type Snapshot = Schemas["Snapshot"];
export type SnapshotCreate = Schemas["SnapshotCreate"];
export type TrendComparison = Schemas["TrendComparison"];
export type TrendComparisonSummary = Schemas["TrendComparisonSummary"];
export type TrendComparisonCreate = Schemas["TrendComparisonCreate"];
export type ObservationChange = Schemas["ObservationChange"];
export type Implication = Schemas["Implication"];

export type ArenaResult = Schemas["ArenaResult"];
export type ArenaSummary = Schemas["ArenaSummary"];
export type ArenaCreate = Schemas["ArenaCreate"];
export type ArenaUpdate = Schemas["ArenaUpdate"];
export type ArenaVariantInput = Schemas["ArenaVariantInput"];
export type ArenaVariantResult = Schemas["ArenaVariantResult"];
export type Improvement = Schemas["Improvement"];

export type RiskScan = Schemas["RiskScan"];
export type RiskScanSummary = Schemas["RiskScanSummary"];
export type RiskScanCreate = Schemas["RiskScanCreate"];
export type RiskFinding = Schemas["RiskFinding"];
export type RiskFindingUpdate = Schemas["RiskFindingUpdate"];
export type FindingCounts = Schemas["FindingCounts"];
export type TextLocation = Schemas["TextLocation"];

export type Asset = Schemas["Asset"];
export type VisionStatus = Schemas["VisionStatus"];
export type VisualObservation = Schemas["VisualObservation"];

export type EvidenceGraph = Schemas["EvidenceGraph"];
export type GraphNode = Schemas["GraphNode"];
export type GraphEdge = Schemas["GraphEdge"];
export type GraphRef = Schemas["GraphRef"];

export type SearchResults = Schemas["SearchResults"];
export type SearchHit = Schemas["SearchHit"];

// v3 (contracts/README §14): population studies, social simulation, graph views
export type ConfirmedReference = Schemas["ConfirmedReference"];
export type ReactionCategory = Schemas["Interview"]["reaction"];
export type InterestRef = Schemas["InterestRef"];
export type PopulationGroup = Schemas["PopulationGroup"];
export type Participant = Schemas["Participant"];
export type Population = Schemas["Population"];
export type PopulationSummary = Schemas["PopulationSummary"];
export type PopulationStudyCreate = Schemas["PopulationStudyCreate"];
export type PopulationStudySummary = Schemas["PopulationStudySummary"];
export type PopulationStudyResult = Schemas["PopulationStudyResult"];
export type Interview = Schemas["Interview"];
export type InterviewAnswer = Schemas["InterviewAnswer"];
export type ReactionDistribution = Schemas["ReactionDistribution"];
export type ThemeCount = Schemas["ThemeCount"];
export type GroupResult = Schemas["GroupResult"];
export type SocialSimulationCreate = Schemas["SocialSimulationCreate"];
export type SocialSimulationSummary = Schemas["SocialSimulationSummary"];
export type SocialSimulationResult = Schemas["SocialSimulationResult"];
export type SocialPost = Schemas["SocialPost"];
export type SocialRoundSummary = Schemas["SocialRoundSummary"];
export type GraphView = Schemas["GraphView"];
export type ViewNode = Schemas["ViewNode"];
export type ViewEdge = Schemas["ViewEdge"];
export type CampaignComparison = Schemas["CampaignComparison"];
