-- What a rule saw, shown to admins (e.g. the text read on screen).
ALTER TABLE events ADD COLUMN detail VARCHAR(300) NULL AFTER score;
