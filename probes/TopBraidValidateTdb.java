import java.nio.file.Files;
import java.nio.file.Path;

import org.apache.jena.query.Dataset;
import org.apache.jena.query.ReadWrite;
import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.rdf.model.Property;
import org.apache.jena.rdf.model.Resource;
import org.apache.jena.riot.RDFDataMgr;
import org.apache.jena.tdb2.TDB2Factory;
import org.topbraid.shacl.validation.ValidationUtil;

/** TopBraid SHACL runner with a disk-backed Jena TDB2 data model. */
public final class TopBraidValidateTdb {
    private static final String SH = "http://www.w3.org/ns/shacl#";

    private TopBraidValidateTdb() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.err.println("usage: TopBraidValidateTdb DATA SHAPES EMPTY_TDB_DIRECTORY");
            System.exit(2);
        }
        Path databasePath = Path.of(args[2]);
        if (Files.exists(databasePath) && Files.list(databasePath).findAny().isPresent()) {
            throw new IllegalArgumentException("TDB directory must be absent or empty: " + databasePath);
        }

        long started = System.nanoTime();
        Dataset dataset = TDB2Factory.connectDataset(databasePath.toString());
        dataset.begin(ReadWrite.WRITE);
        RDFDataMgr.read(dataset.getDefaultModel(), Path.of(args[0]).toUri().toString());
        dataset.commit();
        dataset.end();

        Model shapes = ModelFactory.createDefaultModel();
        RDFDataMgr.read(shapes, Path.of(args[1]).toUri().toString());
        long loaded = System.nanoTime();

        dataset.begin(ReadWrite.READ);
        Resource report;
        long dataTriples;
        try {
            Model data = dataset.getDefaultModel();
            dataTriples = data.size();
            report = ValidationUtil.validateModel(data, shapes, false);
        } finally {
            dataset.end();
            dataset.close();
        }
        long validated = System.nanoTime();

        Property conformsProperty = report.getModel().createProperty(SH + "conforms");
        Property resultProperty = report.getModel().createProperty(SH + "result");
        boolean conforms = report.getRequiredProperty(conformsProperty).getBoolean();
        long results = report.listProperties(resultProperty).toList().size();
        System.out.printf(
                "engine=topbraid-shacl store=tdb2 data_triples=%d shape_triples=%d "
                        + "load_seconds=%.3f validate_seconds=%.3f total_seconds=%.3f "
                        + "conforms=%s results=%d%n",
                dataTriples,
                shapes.size(),
                seconds(loaded - started),
                seconds(validated - loaded),
                seconds(validated - started),
                conforms,
                results);
    }

    private static double seconds(long nanoseconds) {
        return nanoseconds / 1_000_000_000.0;
    }
}
