// schema.sql and the migration files are imported as text so the tests exercise
// the same SQL the README tells people to apply, rather than a copy of it.
declare module "*.sql?raw" {
  const content: string;
  export default content;
}
